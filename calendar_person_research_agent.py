#!/usr/bin/env python3
"""
Calendar Person Research Agent - Combines Google Calendar with Person Research
Extracts meeting information and researches attendees using LinkedIn, Wikipedia, and Tavily
"""
import os
import sys
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Import our existing agents
sys.path.append('/home/guna/Interview')
from agents.ultimate_person_bio_agent import UltimatePersonBioAgent

# Load environment variables
load_dotenv()

# Google Calendar API scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/contacts.readonly',
    'https://www.googleapis.com/auth/gmail.readonly'
]

@dataclass
class AttendeeInfo:
    """Data class to store attendee information"""
    name: str = ""
    email: str = ""
    display_name: str = ""
    company: str = ""
    title: str = ""
    
    def __post_init__(self):
        if self.name:
            self.display_name = self.name
        elif self.email:
            self.display_name = self._extract_name_from_email(self.email)
        else:
            self.display_name = "Unknown"
    
    def _extract_name_from_email(self, email: str) -> str:
        """Extract a readable name from an email address"""
        if '@' in email:
            name_part = email.split('@')[0]
            # Replace dots and underscores with spaces
            name_part = name_part.replace('.', ' ').replace('_', ' ')
            # Capitalize each word
            return ' '.join(word.capitalize() for word in name_part.split())
        return email

@dataclass
class MeetingInfo:
    """Data class to store meeting information"""
    meeting_title: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    attendees: List[AttendeeInfo] = None
    description: str = ""
    location: str = ""
    meeting_id: str = ""
    
    def __post_init__(self):
        if self.attendees is None:
            self.attendees = []

@dataclass
class PersonResearchResult:
    """Data class to store person research results"""
    attendee: AttendeeInfo
    research_summary: str = ""
    linkedin_profiles: List[str] = None
    found_info: bool = False
    
    def __post_init__(self):
        if self.linkedin_profiles is None:
            self.linkedin_profiles = []

class CalendarPersonResearchAgent:
    """Agent that combines Google Calendar with Person Research capabilities"""
    
    def __init__(self, model: str | None = None, temperature: float = 0):
        # Initialize Google Calendar service
        self.calendar_service = None
        self.contacts_service = None
        self.gmail_service = None
        self._initialize_google_services()
        
        # Initialize Person Research Agent
        self.person_agent = UltimatePersonBioAgent(model=model, temperature=temperature)
        
        # Initialize LLM for meeting analysis
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment.")
        
        self.llm = ChatOpenAI(
            temperature=temperature,
            model=model or os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
            openai_api_key=api_key,
        )
    
    def _initialize_google_services(self):
        """Initialize Google Calendar, Contacts, and Gmail services"""
        try:
            creds = None
            token_file = os.getenv('GOOGLE_CALENDAR_TOKEN_FILE', 'token.json')
            credentials_file = os.getenv('GOOGLE_CALENDAR_CREDENTIALS_FILE', 'credentials.json')
            
            # Load existing credentials
            if os.path.exists(token_file):
                creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            
            # If there are no (valid) credentials available, let the user log in
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if not os.path.exists(credentials_file):
                        raise FileNotFoundError(f"Credentials file not found: {credentials_file}")
                    
                    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                    creds = flow.run_local_server(port=0)
                
                # Save the credentials for the next run
                with open(token_file, 'w') as token:
                    token.write(creds.to_json())
            
            # Build services
            self.calendar_service = build('calendar', 'v3', credentials=creds)
            self.contacts_service = build('people', 'v1', credentials=creds)
            self.gmail_service = build('gmail', 'v1', credentials=creds)
            
            print("✅ Google services initialized successfully!")
            
        except Exception as e:
            print(f"❌ Error initializing Google services: {e}")
            raise
    
    def get_next_meeting_info(self) -> Optional[MeetingInfo]:
        """Get information about the next upcoming meeting"""
        try:
            now = datetime.utcnow()
            time_min = now.isoformat() + 'Z'
            time_max = (now + timedelta(days=7)).isoformat() + 'Z'
            
            events_result = self.calendar_service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                maxResults=1,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            if not events:
                return None
            
            event = events[0]
            return self._parse_meeting_info(event)
            
        except Exception as e:
            print(f"❌ Error getting next meeting: {e}")
            return None
    
    def get_meeting_by_id(self, event_id: str) -> Optional[MeetingInfo]:
        """Get specific meeting information by event ID"""
        try:
            event = self.calendar_service.events().get(
                calendarId='primary',
                eventId=event_id
            ).execute()
            
            return self._parse_meeting_info(event)
            
        except Exception as e:
            print(f"❌ Error getting meeting by ID: {e}")
            return None
    
    def search_meetings_by_keyword(self, keyword: str, max_results: int = 5) -> List[MeetingInfo]:
        """Search for meetings by keyword in title or description"""
        try:
            now = datetime.utcnow()
            time_min = (now - timedelta(days=30)).isoformat() + 'Z'
            time_max = (now + timedelta(days=30)).isoformat() + 'Z'
            
            events_result = self.calendar_service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                maxResults=100,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            matching_meetings = []
            
            for event in events:
                title = event.get('summary', '').lower()
                description = event.get('description', '').lower()
                
                if keyword.lower() in title or keyword.lower() in description:
                    meeting_info = self._parse_meeting_info(event)
                    matching_meetings.append(meeting_info)
                    
                    if len(matching_meetings) >= max_results:
                        break
            
            return matching_meetings
            
        except Exception as e:
            print(f"❌ Error searching meetings: {e}")
            return []
    
    def _parse_meeting_info(self, event: Dict[str, Any]) -> MeetingInfo:
        """Parse Google Calendar event into MeetingInfo object"""
        try:
            # Extract basic meeting information
            meeting_title = event.get('summary', 'No Title')
            description = event.get('description', '')
            location = event.get('location', '')
            meeting_id = event.get('id', '')
            
            # Parse start and end times
            start_time = None
            end_time = None
            
            if 'start' in event:
                start = event['start']
                if 'dateTime' in start:
                    start_time = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
                elif 'date' in start:
                    start_time = datetime.fromisoformat(start['date'] + 'T00:00:00+00:00')
            
            if 'end' in event:
                end = event['end']
                if 'dateTime' in end:
                    end_time = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
                elif 'date' in end:
                    end_time = datetime.fromisoformat(end['date'] + 'T23:59:59+00:00')
            
            # Extract attendees
            attendees = []
            if 'attendees' in event:
                for attendee in event['attendees']:
                    email = attendee.get('email', '')
                    name = attendee.get('displayName', '')
                    
                    # Try to get additional info from contacts
                    contact_info = self._get_contact_info(email)
                    
                    attendee_info = AttendeeInfo(
                        name=name or contact_info.get('name', ''),
                        email=email,
                        company=contact_info.get('company', ''),
                        title=contact_info.get('title', '')
                    )
                    attendees.append(attendee_info)
            
            return MeetingInfo(
                meeting_title=meeting_title,
                start_time=start_time,
                end_time=end_time,
                attendees=attendees,
                description=description,
                location=location,
                meeting_id=meeting_id
            )
            
        except Exception as e:
            print(f"❌ Error parsing meeting info: {e}")
            return MeetingInfo()
    
    def _get_contact_info(self, email: str) -> Dict[str, str]:
        """Get additional contact information from Google Contacts"""
        try:
            if not self.contacts_service:
                return {}
            
            # Search for contact by email
            results = self.contacts_service.people().searchContacts(
                query=email,
                readMask='names,emailAddresses,organizations'
            ).execute()
            
            if 'results' in results and results['results']:
                person = results['results'][0]['person']
                
                # Extract name
                name = ""
                if 'names' in person and person['names']:
                    name = person['names'][0].get('displayName', '')
                
                # Extract company and title
                company = ""
                title = ""
                if 'organizations' in person and person['organizations']:
                    org = person['organizations'][0]
                    company = org.get('name', '')
                    title = org.get('title', '')
                
                return {
                    'name': name,
                    'company': company,
                    'title': title
                }
            
            return {}
            
        except Exception as e:
            print(f"❌ Error getting contact info: {e}")
            return {}
    
    def research_meeting_attendees(self, meeting_info: MeetingInfo) -> List[PersonResearchResult]:
        """Research all attendees of a meeting"""
        print(f"🔍 Researching attendees for meeting: {meeting_info.meeting_title}")
        print("=" * 60)
        
        research_results = []
        
        for attendee in meeting_info.attendees:
            # Skip self (your own email)
            if attendee.email and attendee.email == 'gvengalasetti@gmail.com':
                print(f"\n⏭️ Skipping self: {attendee.display_name}")
                continue
                
            print(f"\n👤 Researching: {attendee.display_name}")
            if attendee.email:
                print(f"📧 Email: {attendee.email}")
            if attendee.company:
                print(f"🏢 Company: {attendee.company}")
            if attendee.title:
                print(f"💼 Title: {attendee.title}")
            
            # Create search context
            search_context = f"{attendee.display_name}"
            if attendee.company:
                search_context += f" {attendee.company}"
            if attendee.title:
                search_context += f" {attendee.title}"
            
            # Research the person
            try:
                research_summary = self.person_agent.summarize_person(
                    attendee.display_name, 
                    search_context
                )
                
                result = PersonResearchResult(
                    attendee=attendee,
                    research_summary=research_summary,
                    found_info=True
                )
                
                print(f"✅ Research completed for {attendee.display_name}")
                
            except Exception as e:
                print(f"❌ Error researching {attendee.display_name}: {e}")
                result = PersonResearchResult(
                    attendee=attendee,
                    research_summary=f"Error researching person: {str(e)}",
                    found_info=False
                )
            
            research_results.append(result)
        
        return research_results
    
    def generate_meeting_summary(self, meeting_info: MeetingInfo, research_results: List[PersonResearchResult]) -> str:
        """Generate a comprehensive meeting summary with attendee research and suggested questions"""
        
        # Prepare attendee research summaries
        attendee_summaries = []
        for result in research_results:
            attendee_summaries.append(f"""
**{result.attendee.display_name}**
- Email: {result.attendee.email}
- Company: {result.attendee.company}
- Title: {result.attendee.title}
- Research Summary: {result.research_summary}
""")
        
        # Create comprehensive prompt
        prompt = f"""You are a professional meeting analyst and preparation expert. Generate a comprehensive summary of this meeting with detailed attendee research AND provide intelligent question suggestions for preparation.

**Meeting Information:**
- Title: {meeting_info.meeting_title}
- Start Time: {meeting_info.start_time}
- End Time: {meeting_info.end_time}
- Location: {meeting_info.location}
- Description: {meeting_info.description}

**Attendee Research:**
{chr(10).join(attendee_summaries)}

Please provide a well-structured response with TWO main sections:

## SECTION 1: MEETING ANALYSIS
Include:
1. Meeting overview and purpose
2. Key attendees and their backgrounds
3. Professional insights about each attendee
4. Meeting context and potential topics
5. Any notable connections or relationships between attendees

## SECTION 2: PREPARATION QUESTIONS
Based on the meeting type, attendees' backgrounds, and their expertise, provide:
1. **Opening Questions** (3-5 questions to start the conversation)
2. **Technical/Professional Questions** (5-7 questions about their expertise/field)
3. **Collaboration Questions** (3-5 questions about working together)
4. **Follow-up Questions** (2-3 questions for next steps)
5. **Context-Specific Questions** (questions tailored to the specific meeting type and attendees)

Format the response professionally with clear sections, bullet points, and actionable question suggestions."""

        try:
            response = self.llm.invoke(prompt)
            return response.content
        except Exception as e:
            return f"Error generating meeting summary: {str(e)}"
    
    def analyze_next_meeting(self) -> str:
        """Analyze the next upcoming meeting with attendee research"""
        print("📅 Analyzing next meeting...")
        
        # Get next meeting
        meeting_info = self.get_next_meeting_info()
        if not meeting_info:
            return "No upcoming meetings found."
        
        # Research attendees
        research_results = self.research_meeting_attendees(meeting_info)
        
        # Generate comprehensive summary
        summary = self.generate_meeting_summary(meeting_info, research_results)
        
        return summary
    
    def analyze_meeting_by_id(self, event_id: str) -> str:
        """Analyze a specific meeting by ID with attendee research"""
        print(f"📅 Analyzing meeting ID: {event_id}")
        
        # Get meeting
        meeting_info = self.get_meeting_by_id(event_id)
        if not meeting_info:
            return f"Meeting with ID {event_id} not found."
        
        # Research attendees
        research_results = self.research_meeting_attendees(meeting_info)
        
        # Generate comprehensive summary
        summary = self.generate_meeting_summary(meeting_info, research_results)
        
        return summary
    
    def search_and_analyze_meetings(self, keyword: str) -> str:
        """Search for meetings by keyword and analyze the first one found"""
        print(f"🔍 Searching for meetings with keyword: {keyword}")
        
        # Search meetings
        meetings = self.search_meetings_by_keyword(keyword, max_results=1)
        if not meetings:
            return f"No meetings found with keyword: {keyword}"
        
        # Analyze first meeting
        meeting_info = meetings[0]
        research_results = self.research_meeting_attendees(meeting_info)
        summary = self.generate_meeting_summary(meeting_info, research_results)
        
        return summary
    
    def generate_meeting_type_questions(self, meeting_info: MeetingInfo, research_results: List[PersonResearchResult]) -> str:
        """Generate specific questions based on meeting type and attendees"""
        
        # Determine meeting type from title and description
        meeting_title = meeting_info.meeting_title.lower()
        meeting_desc = meeting_info.description.lower()
        
        meeting_type = "general"
        if any(word in meeting_title for word in ["interview", "interviewing"]):
            meeting_type = "interview"
        elif any(word in meeting_title for word in ["project", "research", "thesis", "master", "phd"]):
            meeting_type = "academic"
        elif any(word in meeting_title for word in ["sales", "business", "client", "customer"]):
            meeting_type = "business"
        elif any(word in meeting_title for word in ["technical", "engineering", "development"]):
            meeting_type = "technical"
        elif any(word in meeting_title for word in ["networking", "coffee", "lunch", "meet"]):
            meeting_type = "networking"
        
        # Prepare attendee context
        attendee_context = []
        for result in research_results:
            attendee_context.append(f"- {result.attendee.display_name} ({result.attendee.title} at {result.attendee.company})")
        
        prompt = f"""You are a meeting preparation expert. Generate intelligent, specific questions for this meeting based on the meeting type and attendees.

**Meeting Details:**
- Title: {meeting_info.meeting_title}
- Type: {meeting_type}
- Description: {meeting_info.description}
- Attendees: {chr(10).join(attendee_context)}

**Attendee Research:**
{chr(10).join([f"**{result.attendee.display_name}**: {result.research_summary[:200]}..." for result in research_results])}

Generate questions specifically tailored for a {meeting_type} meeting with these attendees. Provide:

1. **Opening Questions** (3-4 questions to break the ice and establish rapport)
2. **{meeting_type.title()} Specific Questions** (5-6 questions relevant to this meeting type)
3. **Attendee-Specific Questions** (3-4 questions tailored to each person's expertise/background)
4. **Collaboration Questions** (3-4 questions about working together or next steps)
5. **Follow-up Questions** (2-3 questions for maintaining the relationship)

Make questions specific, actionable, and professional. Avoid generic questions."""

        try:
            response = self.llm.invoke(prompt)
            return response.content
        except Exception as e:
            return f"Error generating meeting questions: {str(e)}"


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Calendar Person Research Agent")
    parser.add_argument("--next", action="store_true", help="Analyze next meeting")
    parser.add_argument("--id", type=str, help="Analyze meeting by ID")
    parser.add_argument("--search", type=str, help="Search and analyze meetings by keyword")
    parser.add_argument("--questions-only", action="store_true", help="Generate only preparation questions")
    args = parser.parse_args()
    
    print("🤖 Initializing Calendar Person Research Agent...")
    
    try:
        agent = CalendarPersonResearchAgent()
        print("✅ Agent initialized successfully!")
        
        if args.next:
            print("\n📅 Analyzing next meeting...")
            if args.questions_only:
                # Get meeting info and research attendees
                meeting_info = agent.get_next_meeting_info()
                if not meeting_info:
                    print("No upcoming meetings found.")
                    return
                research_results = agent.research_meeting_attendees(meeting_info)
                questions = agent.generate_meeting_type_questions(meeting_info, research_results)
                print(f"\n❓ Preparation Questions:\n{questions}")
            else:
                summary = agent.analyze_next_meeting()
                print(f"\n📋 Meeting Analysis:\n{summary}")
            
        elif args.id:
            print(f"\n📅 Analyzing meeting ID: {args.id}")
            if args.questions_only:
                meeting_info = agent.get_meeting_by_id(args.id)
                if not meeting_info:
                    print(f"Meeting with ID {args.id} not found.")
                    return
                research_results = agent.research_meeting_attendees(meeting_info)
                questions = agent.generate_meeting_type_questions(meeting_info, research_results)
                print(f"\n❓ Preparation Questions:\n{questions}")
            else:
                summary = agent.analyze_meeting_by_id(args.id)
                print(f"\n📋 Meeting Analysis:\n{summary}")
            
        elif args.search:
            print(f"\n🔍 Searching for meetings with keyword: {args.search}")
            meetings = agent.search_meetings_by_keyword(args.search, max_results=1)
            if not meetings:
                print(f"No meetings found with keyword: {args.search}")
                return
            
            meeting_info = meetings[0]
            research_results = agent.research_meeting_attendees(meeting_info)
            
            if args.questions_only:
                questions = agent.generate_meeting_type_questions(meeting_info, research_results)
                print(f"\n❓ Preparation Questions:\n{questions}")
            else:
                summary = agent.generate_meeting_summary(meeting_info, research_results)
                print(f"\n📋 Meeting Analysis:\n{summary}")
            
        else:
            print("\n💡 Usage examples:")
            print("  python calendar_person_research_agent.py --next")
            print("  python calendar_person_research_agent.py --next --questions-only")
            print("  python calendar_person_research_agent.py --id <event_id>")
            print("  python calendar_person_research_agent.py --search 'interview'")
            print("  python calendar_person_research_agent.py --search 'interview' --questions-only")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n💡 Make sure you have:")
        print("1. Google Calendar credentials set up")
        print("2. OPENAI_API_KEY set in your environment")
        print("3. TAVILY_API_KEY set for enhanced search (optional)")


if __name__ == "__main__":
    main()
