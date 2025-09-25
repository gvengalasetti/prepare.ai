import os
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import openai
from dotenv import load_dotenv

# LangChain imports for agent functionality
from langchain.agents import Tool, AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

# Load environment variables
load_dotenv()

# Google Calendar API scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/contacts.readonly',  # For accessing contact names
    'https://www.googleapis.com/auth/gmail.readonly'      # Alternative way to get contact info
]

@dataclass
class AttendeeInfo:
    """Data class to store attendee information"""
    name: str = ""
    email: str = ""
    display_name: str = ""  # The name to display (prioritizes name over email)
    
    def __post_init__(self):
        # Set display_name: use name if available, otherwise use email
        if self.name:
            self.display_name = self.name
        elif self.email:
            # Extract name part from email if no name provided
            self.display_name = self._extract_name_from_email(self.email)
        else:
            self.display_name = "Unknown"
    
    def _extract_name_from_email(self, email: str) -> str:
        """Extract a readable name from an email address"""
        if not email:
            return "Unknown"
        
        local_part = email.split('@')[0]
        
        # Remove common suffixes that aren't part of names
        local_part = re.sub(r'\d+$', '', local_part)  # Remove trailing numbers
        local_part = re.sub(r'[._-]+$', '', local_part)  # Remove trailing separators
        
        # Handle different patterns
        if '.' in local_part:
            # Pattern: firstname.lastname or f.lastname
            parts = local_part.split('.')
            if len(parts) == 2:
                first, last = parts
                # Handle initials + last name (e.g., j.smith -> J Smith)
                if len(first) == 1:
                    return f"{first.upper()} {last.title()}"
                else:
                    return f"{first.title()} {last.title()}"
            else:
                # Multiple dots, just title case each part
                return ' '.join(part.title() for part in parts if part)
        
        elif '_' in local_part:
            # Pattern: firstname_lastname
            parts = local_part.split('_')
            return ' '.join(part.title() for part in parts if part)
        
        elif '-' in local_part:
            # Pattern: firstname-lastname
            parts = local_part.split('-')
            return ' '.join(part.title() for part in parts if part)
        
        else:
            # Single word, just title case
            return local_part.title()

@dataclass
class MeetingInfo:
    """Data class to store extracted meeting information"""
    meeting_title: str
    person_names: List[str]
    original_description: str
    meeting_id: str
    start_time: datetime
    end_time: datetime
    attendees: List[AttendeeInfo] = None
    attendee_emails: List[str] = None  # Deprecated, keeping for backward compatibility
    location: str = ""
    organizer_name: str = ""
    organizer_email: str = ""
    organizer: str = ""  # Deprecated, keeping for backward compatibility
    
    def __post_init__(self):
        if self.attendees is None:
            self.attendees = []
        
        # For backward compatibility, populate attendee_emails
        if self.attendee_emails is None:
            self.attendee_emails = [attendee.email for attendee in self.attendees if attendee.email]
        
        # For backward compatibility, set organizer to organizer_email if not set
        if not self.organizer and self.organizer_email:
            self.organizer = self.organizer_email
    
    def get_attendee_display_names(self) -> List[str]:
        """Get list of attendee display names (prioritizing actual names over emails)"""
        return [attendee.display_name for attendee in self.attendees]
    
    def get_attendee_emails(self) -> List[str]:
        """Get list of attendee email addresses"""
        return [attendee.email for attendee in self.attendees if attendee.email]

@dataclass
class DayEventsInfo:
    """Data class to store information about all events in a day"""
    date: str
    total_events: int
    meetings: List[MeetingInfo]
    summary_info: Dict[str, any] = None
    
    def __post_init__(self):
        if self.summary_info is None:
            self.summary_info = {}

class CalendarAgent:
    """Agent for accessing Google Calendar and extracting meeting information"""
    
    def __init__(self):
        self.credentials_file = os.getenv('GOOGLE_CALENDAR_CREDENTIALS_FILE', 'credentials.json')
        self.token_file = os.getenv('GOOGLE_CALENDAR_TOKEN_FILE', 'token.json')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.use_enhanced_extraction = os.getenv('USE_ENHANCED_NAME_EXTRACTION', 'false').lower() == 'true'
        
        if self.openai_api_key:
            openai.api_key = self.openai_api_key
        
        self.service = None
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google Calendar API"""
        creds = None
        
        # Load existing token if available
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
        
        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Google Calendar credentials file not found: {self.credentials_file}\n"
                        "Please download credentials.json from Google Cloud Console"
                    )
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save credentials for next run
            with open(self.token_file, 'w') as token:
                token.write(creds.to_json())
        
        self.service = build('calendar', 'v3', credentials=creds)
        
        # Try to initialize People API service for contact names
        try:
            self.people_service = build('people', 'v1', credentials=creds)
        except Exception as e:
            print(f"Warning: Could not initialize People API: {e}")
            self.people_service = None
        
        # Try to initialize Gmail API service for alternative contact lookup
        try:
            self.gmail_service = build('gmail', 'v1', credentials=creds)
        except Exception as e:
            print(f"Warning: Could not initialize Gmail API: {e}")
            self.gmail_service = None
    
    def get_upcoming_meetings(self, max_results: int = 10) -> List[Dict]:
        """Get upcoming meetings from the primary calendar"""
        try:
            # Get current time in RFC3339 format
            now = datetime.utcnow().isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            return events
            
        except HttpError as error:
            print(f'An error occurred: {error}')
            return []
    
    def get_meeting_by_id(self, event_id: str) -> Optional[Dict]:
        """Get a specific meeting by its ID"""
        try:
            event = self.service.events().get(
                calendarId='primary',
                eventId=event_id
            ).execute()
            return event
        except HttpError as error:
            print(f'An error occurred: {error}')
            return None
    
    def extract_person_names_basic(self, text: str) -> List[str]:
        """Extract person names using basic regex patterns"""
        # Common patterns for names in meeting descriptions
        patterns = [
            r'\bwith\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',  # "with John Smith"
            r'\bmeeting\s+with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',  # "meeting with John Smith"
            r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:will|is|has)',  # "John Smith will"
            r'\bAttendees?:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*)',  # "Attendees: John Smith, Jane Doe"
        ]
        
        names = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if ',' in match:  # Handle comma-separated names
                    names.extend([name.strip() for name in match.split(',')])
                else:
                    names.append(match.strip())
        
        # Remove duplicates and filter out common words
        exclude_words = {'Meeting', 'Call', 'Discussion', 'Review', 'Sync', 'Standup', 'Team'}
        unique_names = []
        for name in names:
            if name not in unique_names and name not in exclude_words:
                unique_names.append(name)
        
        return unique_names
    
    def extract_meeting_info_with_ai(self, description: str, title: str) -> Tuple[str, List[str]]:
        """Use OpenAI to extract meeting title and person names from description"""
        if not self.openai_api_key:
            # Fallback to basic extraction
            return title, self.extract_person_names_basic(description)
        
        try:
            prompt = f"""
            Extract the meeting title and person names from the following meeting description and title.
            
            Meeting Title: {title}
            Meeting Description: {description}
            
            Please provide:
            1. The main meeting title/topic (if different from the calendar title, use the one from description, otherwise use calendar title)
            2. Names of people mentioned in the description (full names when possible)
            
            Return your response in this exact JSON format:
            {{
                "meeting_title": "extracted title",
                "person_names": ["Name 1", "Name 2"]
            }}
            
            Only include actual person names, not company names or generic terms.
            """
            
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            
            result = json.loads(response.choices[0].message.content)
            return result.get("meeting_title", title), result.get("person_names", [])
            
        except Exception as e:
            print(f"Error using AI extraction: {e}")
            # Fallback to basic extraction
            return title, self.extract_person_names_basic(description)
    
    def extract_attendee_info(self, event: Dict) -> Tuple[List[AttendeeInfo], str, str]:
        """Extract attendee information and organizer from event"""
        attendees_info = []
        organizer_name = ""
        organizer_email = ""
        
        # Debug: Print the raw event data to understand the structure
        if os.getenv('DEBUG_CALENDAR_AGENT', '').lower() == 'true':
            print(f"🔍 DEBUG: Raw event data for attendees:")
            print(f"   Organizer: {event.get('organizer', {})}")
            print(f"   Attendees: {event.get('attendees', [])}")
        
        # Extract organizer
        organizer_info = event.get('organizer', {})
        organizer_email = organizer_info.get('email', '')
        organizer_name = organizer_info.get('displayName', '')
        
        # Try alternative fields for organizer name
        if not organizer_name:
            organizer_name = organizer_info.get('name', '')
        
        # If no display name, try to extract from email
        if not organizer_name and organizer_email:
            organizer_name = self._extract_name_from_email(organizer_email)
        
        # Extract attendees
        attendees = event.get('attendees', [])
        for i, attendee in enumerate(attendees):
            email = attendee.get('email', '')
            name = attendee.get('displayName', '')
            
            # Try alternative name fields that might be present
            if not name:
                name = attendee.get('name', '')
            if not name:
                name = attendee.get('cn', '')  # Common Name from some calendar systems
            # Note: attendee.get('organizer') can be True/False, not a dict, so skip this check
            
            # Skip if no email (required field)
            if not email:
                continue
            
            # If no display name found in any field, try to extract a reasonable name from email
            if not name:
                name = self._extract_name_from_email(email)
            
            if os.getenv('DEBUG_CALENDAR_AGENT', '').lower() == 'true':
                print(f"   Attendee {i+1}: email='{email}', extracted_name='{name}', raw_data={attendee}")
            
            attendee_info = AttendeeInfo(
                name=name,
                email=email
            )
            attendees_info.append(attendee_info)
        
        return attendees_info, organizer_name, organizer_email
    
    def _extract_name_from_email(self, email: str) -> str:
        """Extract a readable name from an email address"""
        if not email:
            return "Unknown"
        
        local_part = email.split('@')[0]
        
        # Remove common suffixes that aren't part of names
        local_part = re.sub(r'\d+$', '', local_part)  # Remove trailing numbers
        local_part = re.sub(r'[._-]+$', '', local_part)  # Remove trailing separators
        
        # Handle different patterns
        if '.' in local_part:
            # Pattern: firstname.lastname or f.lastname
            parts = local_part.split('.')
            if len(parts) == 2:
                first, last = parts
                # Handle initials + last name (e.g., j.smith -> J Smith)
                if len(first) == 1:
                    return f"{first.upper()} {last.title()}"
                else:
                    return f"{first.title()} {last.title()}"
            else:
                # Multiple dots, just title case each part
                return ' '.join(part.title() for part in parts if part)
        
        elif '_' in local_part:
            # Pattern: firstname_lastname
            parts = local_part.split('_')
            return ' '.join(part.title() for part in parts if part)
        
        elif '-' in local_part:
            # Pattern: firstname-lastname
            parts = local_part.split('-')
            return ' '.join(part.title() for part in parts if part)
        
        else:
            # Single word - try to split camelCase or detect common patterns
            return self._smart_split_name(local_part.title())
    
    def _smart_split_name(self, name: str) -> str:
        """Smart splitting of combined names like 'matthewincupertino' or camelCase"""
        # Handle camelCase (e.g., johnSmith -> John Smith)
        if re.search(r'[a-z][A-Z]', name):
            # Split on lowercase followed by uppercase
            parts = re.findall(r'[A-Z][a-z]*|[a-z]+', name)
            return ' '.join(parts)
        
        # Try to detect common name patterns in concatenated strings
        # This is basic - for production, you might want a more sophisticated approach
        common_prefixes = ['mr', 'ms', 'dr', 'prof']
        name_lower = name.lower()
        
        # Check for common prefixes
        for prefix in common_prefixes:
            if name_lower.startswith(prefix) and len(name) > len(prefix):
                return f"{prefix.title()} {name[len(prefix):].title()}"
        
        # Try to detect if it might be firstname+location (like matthewincupertino)
        common_locations = ['in', 'san', 'los', 'new', 'north', 'south', 'east', 'west']
        for loc in common_locations:
            if loc in name_lower and len(name) > len(loc) + 3:
                # Try to split at the location
                idx = name_lower.find(loc)
                if idx > 2:  # Make sure there's a reasonable first name part
                    first_part = name[:idx]
                    second_part = name[idx:]
                    return f"{first_part.title()} {second_part.title()}"
        
        # If no pattern detected, return as-is (title cased)
        return name
    
    def get_contact_name_from_people_api(self, email: str) -> Optional[str]:
        """Try to get the contact name from Google People API"""
        if not self.people_service:
            return None
        
        try:
            # Search for the contact by email
            results = self.people_service.people().searchContacts(
                query=email,
                readMask='names,emailAddresses'
            ).execute()
            
            contacts = results.get('results', [])
            
            for contact in contacts:
                person = contact.get('person', {})
                email_addresses = person.get('emailAddresses', [])
                
                # Check if this contact has the matching email
                for email_addr in email_addresses:
                    if email_addr.get('value', '').lower() == email.lower():
                        names = person.get('names', [])
                        if names:
                            # Use the first name entry
                            name_data = names[0]
                            display_name = name_data.get('displayName', '')
                            if display_name:
                                return display_name
                            
                            # Fallback to constructing name from parts
                            given_name = name_data.get('givenName', '')
                            family_name = name_data.get('familyName', '')
                            if given_name or family_name:
                                return f"{given_name} {family_name}".strip()
            
            return None
            
        except Exception as e:
            if os.getenv('DEBUG_CALENDAR_AGENT', '').lower() == 'true':
                print(f"People API search failed for {email}: {e}")
            return None
    
    def get_contact_name_from_gmail_api(self, email: str) -> Optional[str]:
        """Try to get contact name from Gmail API by searching for emails from this address"""
        if not self.gmail_service:
            return None
        
        try:
            # Search for emails from this address to get the display name
            query = f"from:{email}"
            results = self.gmail_service.users().messages().list(
                userId='me',
                q=query,
                maxResults=5  # Just need a few to find the name
            ).execute()
            
            messages = results.get('messages', [])
            
            for message in messages:
                # Get the message details
                msg = self.gmail_service.users().messages().get(
                    userId='me',
                    id=message['id'],
                    format='metadata',
                    metadataHeaders=['From']
                ).execute()
                
                headers = msg.get('payload', {}).get('headers', [])
                
                for header in headers:
                    if header.get('name', '').lower() == 'from':
                        from_field = header.get('value', '')
                        
                        # Parse "Display Name <email@domain.com>" format
                        if '<' in from_field and '>' in from_field:
                            name_part = from_field.split('<')[0].strip()
                            if name_part and name_part != email:
                                # Remove quotes if present
                                name_part = name_part.strip('"\'')
                                return name_part
                        
                        # Parse "email@domain.com (Display Name)" format
                        elif '(' in from_field and ')' in from_field:
                            name_part = from_field.split('(')[1].split(')')[0].strip()
                            if name_part and name_part != email:
                                return name_part
            
            return None
            
        except Exception as e:
            if os.getenv('DEBUG_CALENDAR_AGENT', '').lower() == 'true':
                print(f"Gmail API search failed for {email}: {e}")
            return None
    
    def get_enhanced_event_with_names(self, event_id: str) -> Optional[Dict]:
        """Get event with enhanced name information using multiple API calls"""
        try:
            # Get the event with expanded attendee information
            event = self.service.events().get(
                calendarId='primary',
                eventId=event_id,
                # Request additional fields that might contain names
                fields='*'
            ).execute()
            
            return event
            
        except HttpError as error:
            print(f'Error getting enhanced event: {error}')
            return None
    
    def extract_attendee_info_enhanced(self, event: Dict) -> Tuple[List[AttendeeInfo], str, str]:
        """Enhanced attendee extraction that tries multiple methods to get names"""
        attendees_info = []
        organizer_name = ""
        organizer_email = ""
        
        # Debug: Print the raw event data to understand the structure
        if os.getenv('DEBUG_CALENDAR_AGENT', '').lower() == 'true':
            print(f"🔍 DEBUG Enhanced: Raw event data for attendees:")
            print(f"   Organizer: {event.get('organizer', {})}")
            print(f"   Attendees: {event.get('attendees', [])}")
        
        # Extract organizer with enhanced name lookup
        organizer_info = event.get('organizer', {})
        organizer_email = organizer_info.get('email', '')
        organizer_name = organizer_info.get('displayName', '')
        
        # Try alternative fields for organizer name
        if not organizer_name:
            organizer_name = organizer_info.get('name', '')
        
        # Try People API for organizer
        if not organizer_name and organizer_email and self.people_service:
            api_name = self.get_contact_name_from_people_api(organizer_email)
            if api_name:
                organizer_name = api_name
        
        # If still no display name, extract from email
        if not organizer_name and organizer_email:
            organizer_name = self._extract_name_from_email(organizer_email)
        
        # Extract attendees with enhanced name lookup
        attendees = event.get('attendees', [])
        for i, attendee in enumerate(attendees):
            email = attendee.get('email', '')
            name = attendee.get('displayName', '')
            
            # Try alternative name fields
            if not name:
                name = attendee.get('name', '')
            if not name:
                name = attendee.get('cn', '')
            
            # Skip if no email (required field)
            if not email:
                continue
            
            # Try People API for this attendee
            if not name and self.people_service:
                api_name = self.get_contact_name_from_people_api(email)
                if api_name:
                    name = api_name
            
            # Try Gmail API for this attendee (alternative method)
            if not name and self.gmail_service:
                gmail_name = self.get_contact_name_from_gmail_api(email)
                if gmail_name:
                    name = gmail_name
            
            # If still no display name found, extract from email
            if not name:
                name = self._extract_name_from_email(email)
            
            if os.getenv('DEBUG_CALENDAR_AGENT', '').lower() == 'true':
                print(f"   Enhanced Attendee {i+1}: email='{email}', final_name='{name}', raw_data={attendee}")
            
            attendee_info = AttendeeInfo(
                name=name,
                email=email
            )
            attendees_info.append(attendee_info)
        
        return attendees_info, organizer_name, organizer_email
    
    def extract_attendee_emails(self, event: Dict) -> Tuple[List[str], str]:
        """Legacy method for backward compatibility"""
        attendees_info, _, organizer_email = self.extract_attendee_info(event)
        attendee_emails = [attendee.email for attendee in attendees_info]
        return attendee_emails, organizer_email

    def process_meeting(self, event: Dict) -> MeetingInfo:
        """Process a meeting event and extract relevant information"""
        title = event.get('summary', 'No Title')
        description = event.get('description', '')
        event_id = event.get('id', '')
        location = event.get('location', '')
        
        # Parse start and end times
        start = event.get('start', {})
        end = event.get('end', {})
        
        start_time = None
        end_time = None
        
        if 'dateTime' in start:
            start_time = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
        elif 'date' in start:
            start_time = datetime.fromisoformat(start['date'])
        
        if 'dateTime' in end:
            end_time = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
        elif 'date' in end:
            end_time = datetime.fromisoformat(end['date'])
        
        # Extract meeting info
        extracted_title, person_names = self.extract_meeting_info_with_ai(description, title)
        
        # Extract attendee information and organizer
        attendees_info, organizer_name, organizer_email = self.extract_attendee_info(event)
        
        return MeetingInfo(
            meeting_title=extracted_title,
            person_names=person_names,
            original_description=description,
            meeting_id=event_id,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees_info,
            location=location,
            organizer_name=organizer_name,
            organizer_email=organizer_email
        )
    
    def process_meeting_enhanced(self, event: Dict) -> MeetingInfo:
        """Process a meeting event with enhanced name extraction using multiple API methods"""
        title = event.get('summary', 'No Title')
        description = event.get('description', '')
        event_id = event.get('id', '')
        location = event.get('location', '')
        
        # Parse start and end times
        start = event.get('start', {})
        end = event.get('end', {})
        
        start_time = None
        end_time = None
        
        if 'dateTime' in start:
            start_time = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
        elif 'date' in start:
            start_time = datetime.fromisoformat(start['date'])
        
        if 'dateTime' in end:
            end_time = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
        elif 'date' in end:
            end_time = datetime.fromisoformat(end['date'])
        
        # Extract meeting info
        extracted_title, person_names = self.extract_meeting_info_with_ai(description, title)
        
        # Try to get enhanced event data first
        enhanced_event = self.get_enhanced_event_with_names(event_id)
        if enhanced_event:
            event = enhanced_event
        
        # Extract attendee information using enhanced method
        attendees_info, organizer_name, organizer_email = self.extract_attendee_info_enhanced(event)
        
        return MeetingInfo(
            meeting_title=extracted_title,
            person_names=person_names,
            original_description=description,
            meeting_id=event_id,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees_info,
            location=location,
            organizer_name=organizer_name,
            organizer_email=organizer_email
        )
    
    def set_enhanced_extraction(self, enabled: bool):
        """Enable or disable enhanced name extraction using People API"""
        self.use_enhanced_extraction = enabled
        if enabled and not self.people_service:
            print("⚠️  Warning: Enhanced extraction enabled but People API is not available")
        print(f"✅ Enhanced name extraction {'enabled' if enabled else 'disabled'}")
    
    def get_next_meeting_info(self) -> Optional[MeetingInfo]:
        """Get information about the next upcoming meeting"""
        meetings = self.get_upcoming_meetings(max_results=1)
        
        if not meetings:
            return None
        
        next_meeting = meetings[0]
        return self.process_meeting(next_meeting)
    
    def get_meeting_info_by_id(self, event_id: str) -> Optional[MeetingInfo]:
        """Get meeting information for a specific event ID"""
        event = self.get_meeting_by_id(event_id)
        
        if not event:
            return None
        
        return self.process_meeting(event)
    
    def search_meetings_by_keyword(self, keyword: str, max_results: int = 5) -> List[MeetingInfo]:
        """Search for meetings containing a specific keyword"""
        try:
            # Get events from the last 30 days and next 30 days
            time_min = (datetime.utcnow() - timedelta(days=30)).isoformat() + 'Z'
            time_max = (datetime.utcnow() + timedelta(days=30)).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results * 2,  # Get more to filter
                singleEvents=True,
                orderBy='startTime',
                q=keyword
            ).execute()
            
            events = events_result.get('items', [])
            
            # Process and filter events
            meeting_infos = []
            for event in events:
                if len(meeting_infos) >= max_results:
                    break
                
                meeting_info = self.process_meeting(event)
                meeting_infos.append(meeting_info)
            
            return meeting_infos
            
        except HttpError as error:
            print(f'An error occurred: {error}')
            return []
    
    def get_events_for_day(self, target_date: str) -> DayEventsInfo:
        """
        Get all events for a specific day and analyze them.
        
        Args:
            target_date: Date in YYYY-MM-DD format (e.g., '2024-01-15')
        
        Returns:
            DayEventsInfo object with all events and analysis
        """
        try:
            # Parse the target date
            date_obj = datetime.strptime(target_date, '%Y-%m-%d')
            
            # Set time range for the day (start and end of day in UTC)
            time_min = date_obj.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
            time_max = date_obj.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Process all events (use enhanced extraction if enabled)
            meetings = []
            for event in events:
                if self.use_enhanced_extraction:
                    meeting_info = self.process_meeting_enhanced(event)
                else:
                    meeting_info = self.process_meeting(event)
                meetings.append(meeting_info)
            
            # Generate summary information
            summary_info = self._analyze_day_events(meetings, target_date)
            
            return DayEventsInfo(
                date=target_date,
                total_events=len(meetings),
                meetings=meetings,
                summary_info=summary_info
            )
            
        except ValueError as e:
            print(f"Invalid date format: {e}. Please use YYYY-MM-DD format.")
            return DayEventsInfo(target_date, 0, [], {"error": "Invalid date format"})
        except HttpError as error:
            print(f'An error occurred: {error}')
            return DayEventsInfo(target_date, 0, [], {"error": str(error)})
    
    def _analyze_day_events(self, meetings: List[MeetingInfo], date: str) -> Dict[str, any]:
        """Analyze all events for a day and generate summary information"""
        if not meetings:
            return {"summary": "No events scheduled for this day"}
        
        # Basic statistics
        total_meetings = len(meetings)
        total_attendees = set()
        all_descriptions = []
        meeting_duration_total = timedelta()
        
        # Collect all unique attendees and descriptions
        for meeting in meetings:
            all_descriptions.append(meeting.original_description)
            # Use new attendee structure
            for attendee in meeting.attendees:
                if attendee.email:
                    total_attendees.add(attendee.email)
            if meeting.start_time and meeting.end_time:
                duration = meeting.end_time - meeting.start_time
                meeting_duration_total += duration
        
        # Use AI to analyze the day's events if OpenAI is available
        ai_analysis = ""
        if self.openai_api_key and all_descriptions:
            ai_analysis = self._get_ai_day_analysis(meetings, date)
        
        return {
            "summary": f"{total_meetings} meetings scheduled",
            "total_unique_attendees": len(total_attendees),
            "attendee_emails": list(total_attendees),
            "total_meeting_time": str(meeting_duration_total),
            "ai_analysis": ai_analysis,
            "meeting_titles": [m.meeting_title for m in meetings]
        }
    
    def _get_ai_day_analysis(self, meetings: List[MeetingInfo], date: str) -> str:
        """Use AI to analyze the day's meetings and provide insights"""
        try:
            # Prepare meeting data for AI analysis
            meeting_summaries = []
            for meeting in meetings:
                summary = {
                    "title": meeting.meeting_title,
                    "time": f"{meeting.start_time.strftime('%H:%M') if meeting.start_time else 'Unknown'} - {meeting.end_time.strftime('%H:%M') if meeting.end_time else 'Unknown'}",
                    "attendees": len(meeting.attendees),
                    "attendee_names": meeting.get_attendee_display_names(),
                    "description_preview": meeting.original_description[:200] + "..." if len(meeting.original_description) > 200 else meeting.original_description,
                    "location": meeting.location,
                    "organizer": meeting.organizer_name or meeting.organizer_email
                }
                meeting_summaries.append(summary)
            
            prompt = f"""
            Analyze the following day's calendar events for {date} and provide insights:
            
            {json.dumps(meeting_summaries, indent=2)}
            
            Please provide:
            1. A brief summary of the day's schedule
            2. Key themes or patterns you notice
            3. Potential scheduling conflicts or busy periods
            4. Notable attendees or important meetings
            5. Any recommendations for the day
            
            Keep the analysis concise but insightful (max 300 words).
            """
            
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            return f"AI analysis unavailable: {str(e)}"
    
    def extract_description_info(self, meeting_id: str) -> Dict[str, any]:
        """
        Extract detailed information from a meeting's description using AI.
        
        Args:
            meeting_id: The event ID to analyze
            
        Returns:
            Dictionary with extracted information
        """
        event = self.get_meeting_by_id(meeting_id)
        if not event:
            return {"error": "Meeting not found"}
        
        description = event.get('description', '')
        title = event.get('summary', 'No Title')
        
        if not description:
            return {"info": "No description available"}
        
        if not self.openai_api_key:
            return {"info": "AI analysis not available - OpenAI API key not set"}
        
        try:
            prompt = f"""
            Analyze the following meeting description and extract key information:
            
            Meeting Title: {title}
            Description: {description}
            
            Please extract and categorize:
            1. Key topics or agenda items
            2. Action items or tasks mentioned
            3. Important dates or deadlines
            4. Technology, tools, or systems mentioned
            5. Business objectives or goals
            6. Contact information (emails, phone numbers)
            7. Links or resources mentioned
            8. Meeting type/purpose
            
            Return the information in a structured JSON format with these categories.
            Only include categories that have relevant information.
            """
            
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500
            )
            
            try:
                extracted_info = json.loads(response.choices[0].message.content)
                return {
                    "extracted_info": extracted_info,
                    "original_description": description,
                    "meeting_title": title
                }
            except json.JSONDecodeError:
                return {
                    "extracted_info": response.choices[0].message.content,
                    "original_description": description,
                    "meeting_title": title
                }
            
        except Exception as e:
            return {"error": f"AI extraction failed: {str(e)}"}
    
    def get_attendee_info_for_day(self, target_date: str) -> Dict[str, any]:
        """
        Get detailed attendee information for all meetings in a day.
        
        Args:
            target_date: Date in YYYY-MM-DD format
            
        Returns:
            Dictionary with attendee analysis
        """
        day_events = self.get_events_for_day(target_date)
        
        if day_events.total_events == 0:
            return {"message": "No events found for this date"}
        
        # Collect all attendee information
        attendee_frequency = {}
        attendee_name_mapping = {}  # Map emails to display names
        meeting_attendee_mapping = {}
        
        for meeting in day_events.meetings:
            # Create attendee list with names prioritized
            attendee_details = []
            for attendee in meeting.attendees:
                attendee_details.append({
                    "name": attendee.display_name,
                    "email": attendee.email
                })
                
                # Track attendee frequency and name mapping
                if attendee.email:
                    attendee_frequency[attendee.email] = attendee_frequency.get(attendee.email, 0) + 1
                    attendee_name_mapping[attendee.email] = attendee.display_name
            
            meeting_attendee_mapping[meeting.meeting_title] = {
                "attendees": attendee_details,
                "attendee_names": meeting.get_attendee_display_names(),
                "attendee_emails": meeting.get_attendee_emails(),
                "organizer_name": meeting.organizer_name,
                "organizer_email": meeting.organizer_email,
                "time": f"{meeting.start_time.strftime('%H:%M') if meeting.start_time else 'Unknown'}"
            }
        
        # Find most frequent attendees with their display names
        frequent_attendees = []
        for email, count in sorted(attendee_frequency.items(), key=lambda x: x[1], reverse=True)[:10]:
            display_name = attendee_name_mapping.get(email, email)
            frequent_attendees.append({
                "name": display_name,
                "email": email,
                "meeting_count": count
            })
        
        return {
            "date": target_date,
            "total_meetings": day_events.total_events,
            "unique_attendees": len(attendee_frequency),
            "meeting_attendee_details": meeting_attendee_mapping,
            "most_frequent_attendees": frequent_attendees,
            "all_attendee_emails": list(attendee_frequency.keys()),
            "all_attendee_names": list(attendee_name_mapping.values())
        }
    
    def create_calendar_agent_tools(self):
        """Create LangChain tools for the calendar agent"""
        def get_day_events_tool(date_input: str) -> str:
            """Get all events for a specific day. Input format: YYYY-MM-DD"""
            try:
                day_info = self.get_events_for_day(date_input.strip())
                return json.dumps(asdict(day_info), indent=2, default=str)
            except Exception as e:
                return f"Error: {str(e)}"
        
        def extract_meeting_description_tool(meeting_id: str) -> str:
            """Extract detailed information from a meeting description. Input: meeting ID"""
            try:
                info = self.extract_description_info(meeting_id.strip())
                return json.dumps(info, indent=2, default=str)
            except Exception as e:
                return f"Error: {str(e)}"
        
        def get_attendees_for_day_tool(date_input: str) -> str:
            """Get attendee information for all meetings in a day. Input format: YYYY-MM-DD"""
            try:
                attendee_info = self.get_attendee_info_for_day(date_input.strip())
                return json.dumps(attendee_info, indent=2, default=str)
            except Exception as e:
                return f"Error: {str(e)}"
        
        tools = [
            Tool(
                name="GetDayEvents",
                func=get_day_events_tool,
                description="Get all calendar events for a specific day with AI analysis. Input should be a date in YYYY-MM-DD format (e.g., '2024-01-15'). Returns detailed information about all meetings, attendees, and AI insights."
            ),
            Tool(
                name="ExtractMeetingDescription",
                func=extract_meeting_description_tool,
                description="Extract and analyze information from a meeting's description using AI. Input should be a meeting/event ID. Returns structured information about agenda items, action items, contacts, and other details."
            ),
            Tool(
                name="GetAttendeeInfo",
                func=get_attendees_for_day_tool,
                description="Get detailed attendee information and email addresses for all meetings in a specific day. Input should be a date in YYYY-MM-DD format. Returns attendee analysis, email addresses, and meeting participation details."
            )
        ]
        
        return tools
    
    def create_langchain_agent(self):
        """Create a LangChain agent with calendar tools"""
        if not self.openai_api_key:
            raise ValueError("OpenAI API key required for LangChain agent")
        
        # Initialize LLM
        llm = ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0.1,
            api_key=self.openai_api_key
        )
        
        # Get calendar tools
        tools = self.create_calendar_agent_tools()
        
        # Create prompt template
        prompt = PromptTemplate(
            input_variables=["tools", "tool_names", "input", "agent_scratchpad"],
            template="""You are a helpful calendar assistant that can analyze calendar events, extract information from meeting descriptions, and provide insights about attendees.

You have access to the following tools:
{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Important notes:
- When extracting meeting information, provide clear summaries
- For attendee information, organize by meeting and highlight key participants
- Always format dates as YYYY-MM-DD when using tools
- Provide insights and analysis, not just raw data

Begin!

Question: {input}
Thought: {agent_scratchpad}"""
        )
        
        # Create agent
        agent = create_react_agent(llm, tools, prompt)
        
        # Create agent executor
        agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=5
        )
        
        return agent_executor

def main():
    """Example usage of the CalendarAgent"""
    try:
        agent = CalendarAgent()
        
        print("🤖 Calendar Agent initialized successfully!")
        print("\n" + "="*50)
        
        # Get next meeting
        print("📅 Getting next meeting information...")
        next_meeting = agent.get_next_meeting_info()
        
        if next_meeting:
            print(f"\n✅ Next Meeting Found:")
            print(f"   📋 Title: {next_meeting.meeting_title}")
            print(f"   👥 Attendees: {', '.join(next_meeting.get_attendee_display_names()) if next_meeting.attendees else 'None found'}")
            print(f"   🏢 Organizer: {next_meeting.organizer_name or next_meeting.organizer_email}")
            print(f"   🕐 Start: {next_meeting.start_time}")
            print(f"   📝 Description: {next_meeting.original_description[:100]}...")
        else:
            print("   ❌ No upcoming meetings found")
        
        print("\n" + "="*50)
        
        # Test new day events functionality
        print("📅 Testing day events analysis...")
        today = datetime.now().strftime('%Y-%m-%d')
        print(f"Getting events for today ({today})...")
        
        day_events = agent.get_events_for_day(today)
        if day_events.total_events > 0:
            print(f"\n✅ Found {day_events.total_events} events for today:")
            print(f"   📊 Summary: {day_events.summary_info.get('summary', 'N/A')}")
            print(f"   👥 Unique attendees: {day_events.summary_info.get('total_unique_attendees', 0)}")
            print(f"   🕒 Total meeting time: {day_events.summary_info.get('total_meeting_time', '0:00:00')}")
            
            if day_events.summary_info.get('ai_analysis'):
                print(f"\n🤖 AI Analysis:\n{day_events.summary_info['ai_analysis']}")
            
            # Show attendee details
            print("\n📧 Testing attendee information...")
            attendee_info = agent.get_attendee_info_for_day(today)
            if attendee_info.get('all_attendee_names'):
                print(f"   👥 Attendee names: {', '.join(attendee_info['all_attendee_names'][:5])}...")  # Show first 5
                if attendee_info.get('most_frequent_attendees'):
                    frequent_names = [f"{att['name']} ({att['meeting_count']} meetings)" for att in attendee_info['most_frequent_attendees'][:3]]
                    print(f"   🔄 Most frequent attendees: {', '.join(frequent_names)}")
        else:
            print(f"   ❌ No events found for today ({today})")
        
        print("\n" + "="*50)
        
        # Test LangChain agent
        print("🤖 Testing LangChain Calendar Agent...")
        try:
            langchain_agent = agent.create_langchain_agent()
            print("✅ LangChain agent created successfully!")
            
            # Test with a sample query
            print("\n🔍 Testing agent query...")
            test_query = f"What meetings do I have today ({today})? Give me a summary with attendee information."
            result = langchain_agent.invoke({"input": test_query})
            print(f"🎯 Agent Response: {result['output']}")
            
        except Exception as e:
            print(f"⚠️ LangChain agent test failed: {e}")
        
        print("\n" + "="*50)
        
        # Search for meetings with "interview" keyword
        print("🔍 Searching for meetings with 'interview' keyword...")
        interview_meetings = agent.search_meetings_by_keyword("interview", max_results=3)
        
        if interview_meetings:
            print(f"\n✅ Found {len(interview_meetings)} interview-related meetings:")
            for i, meeting in enumerate(interview_meetings, 1):
                print(f"\n   {i}. 📋 {meeting.meeting_title}")
                print(f"      👥 Attendees: {', '.join(meeting.get_attendee_display_names()) if meeting.attendees else 'None found'}")
                print(f"      📧 Emails: {', '.join(meeting.get_attendee_emails()) if meeting.attendees else 'None found'}")
                print(f"      🕐 Time: {meeting.start_time}")
                print(f"      🏢 Organizer: {meeting.organizer_name or meeting.organizer_email}")
        else:
            print("   ❌ No interview meetings found")
            
    except FileNotFoundError as e:
        print(f"❌ Setup Error: {e}")
        print("\n💡 To get started:")
        print("1. Go to Google Cloud Console")
        print("2. Enable Google Calendar API")
        print("3. Create credentials (OAuth 2.0 Client ID)")
        print("4. Download credentials.json to this directory")
        print("5. Set up your .env file with API keys")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
