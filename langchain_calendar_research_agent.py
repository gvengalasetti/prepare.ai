#!/usr/bin/env python3
"""
LangChain Calendar Person Research Agent
Wraps calendar and person research capabilities as LangChain tools for LLM decision making
"""
import os
import sys
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Type
from dataclasses import dataclass, asdict
from pydantic import BaseModel, Field

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.tools import BaseTool, StructuredTool, tool
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import HumanMessage, AIMessage

# Import our existing agents
sys.path.append('/home/guna/Interview')
from agents.calendar_person_research_agent import CalendarPersonResearchAgent, MeetingInfo, AttendeeInfo, PersonResearchResult
from agents.ultimate_person_bio_agent import UltimatePersonBioAgent

# Load environment variables
load_dotenv()


# Pydantic schemas for tool inputs
class GetNextMeetingInput(BaseModel):
    """Input schema for getting next meeting - no parameters needed"""
    pass

class SearchMeetingsInput(BaseModel):
    """Input schema for searching meetings"""
    keyword: str = Field(description="The keyword to search for in meeting titles or descriptions")

class GetMeetingByIdInput(BaseModel):
    """Input schema for getting meeting by ID"""
    event_id: str = Field(description="The Google Calendar event ID")

class ResearchPersonInput(BaseModel):
    """Input schema for researching a person"""
    name: str = Field(description="The person's name to research")
    context: str = Field(default="", description="Optional context or description about the person")

class ResearchMeetingAttendeesInput(BaseModel):
    """Input schema for researching meeting attendees"""
    event_id: str = Field(description="The Google Calendar event ID")

class GenerateMeetingSummaryInput(BaseModel):
    """Input schema for generating meeting summary"""
    event_id: str = Field(description="The Google Calendar event ID")

class GenerateMeetingQuestionsInput(BaseModel):
    """Input schema for generating meeting questions"""
    event_id: str = Field(description="The Google Calendar event ID")

class AnalyzeNextMeetingInput(BaseModel):
    """Input schema for analyzing next meeting - no parameters needed"""
    pass


def create_calendar_tools(calendar_agent: CalendarPersonResearchAgent, person_agent: UltimatePersonBioAgent):
    """Create all calendar and research tools with proper schemas"""
    
    def get_next_meeting() -> str:
        """Get information about the next upcoming meeting from Google Calendar"""
        try:
            meeting_info = calendar_agent.get_next_meeting_info()
            if not meeting_info:
                return "No upcoming meetings found."
            
            # Format meeting info for display
            result = f"Next Meeting: {meeting_info.meeting_title}\n"
            result += f"Start Time: {meeting_info.start_time}\n"
            result += f"End Time: {meeting_info.end_time}\n"
            result += f"Location: {meeting_info.location}\n"
            result += f"Description: {meeting_info.description}\n"
            result += f"Meeting ID: {meeting_info.meeting_id}\n"
            
            if meeting_info.attendees:
                result += f"Attendees ({len(meeting_info.attendees)}):\n"
                for attendee in meeting_info.attendees:
                    result += f"- {attendee.display_name} ({attendee.email})\n"
                    if attendee.company:
                        result += f"  Company: {attendee.company}\n"
                    if attendee.title:
                        result += f"  Title: {attendee.title}\n"
            
            return result
            
        except Exception as e:
            return f"Error getting next meeting: {str(e)}"

    def search_meetings(keyword: str) -> str:
        """Search for meetings by keyword in title or description"""
        try:
            meetings = calendar_agent.search_meetings_by_keyword(keyword, max_results=5)
            if not meetings:
                return f"No meetings found with keyword: {keyword}"
            
            result = f"Found {len(meetings)} meetings with keyword '{keyword}':\n\n"
            
            for i, meeting in enumerate(meetings, 1):
                result += f"{i}. {meeting.meeting_title}\n"
                result += f"   Start: {meeting.start_time}\n"
                result += f"   End: {meeting.end_time}\n"
                result += f"   Location: {meeting.location}\n"
                result += f"   ID: {meeting.meeting_id}\n"
                if meeting.attendees:
                    result += f"   Attendees: {', '.join([a.display_name for a in meeting.attendees])}\n"
                result += "\n"
            
            return result
            
        except Exception as e:
            return f"Error searching meetings: {str(e)}"

    def get_meeting_by_id(event_id: str) -> str:
        """Get detailed information about a specific meeting by its event ID"""
        try:
            meeting_info = calendar_agent.get_meeting_by_id(event_id)
            if not meeting_info:
                return f"Meeting with ID {event_id} not found."
            
            # Format meeting info for display
            result = f"Meeting: {meeting_info.meeting_title}\n"
            result += f"Start Time: {meeting_info.start_time}\n"
            result += f"End Time: {meeting_info.end_time}\n"
            result += f"Location: {meeting_info.location}\n"
            result += f"Description: {meeting_info.description}\n"
            result += f"Meeting ID: {meeting_info.meeting_id}\n"
            
            if meeting_info.attendees:
                result += f"Attendees ({len(meeting_info.attendees)}):\n"
                for attendee in meeting_info.attendees:
                    result += f"- {attendee.display_name} ({attendee.email})\n"
                    if attendee.company:
                        result += f"  Company: {attendee.company}\n"
                    if attendee.title:
                        result += f"  Title: {attendee.title}\n"
            
            return result
            
        except Exception as e:
            return f"Error getting meeting by ID: {str(e)}"

    def research_person(name: str, context: str = "") -> str:
        """Research a person using LinkedIn, Wikipedia, and web search"""
        try:
            summary = person_agent.summarize_person(name, context)
            return summary
            
        except Exception as e:
            return f"Error researching person: {str(e)}"

    def research_meeting_attendees(event_id: str) -> str:
        """Research all attendees of a specific meeting"""
        try:
            # Get meeting info
            meeting_info = calendar_agent.get_meeting_by_id(event_id)
            if not meeting_info:
                return f"Meeting with ID {event_id} not found."
            
            # Research attendees
            research_results = calendar_agent.research_meeting_attendees(meeting_info)
            
            result = f"Research Results for Meeting: {meeting_info.meeting_title}\n"
            result += "=" * 60 + "\n\n"
            
            for research_result in research_results:
                result += f"👤 {research_result.attendee.display_name}\n"
                result += f"📧 Email: {research_result.attendee.email}\n"
                if research_result.attendee.company:
                    result += f"🏢 Company: {research_result.attendee.company}\n"
                if research_result.attendee.title:
                    result += f"💼 Title: {research_result.attendee.title}\n"
                result += f"📋 Research Summary:\n{research_result.research_summary}\n"
                result += "-" * 40 + "\n\n"
            
            return result
            
        except Exception as e:
            return f"Error researching meeting attendees: {str(e)}"

    def generate_meeting_summary(event_id: str) -> str:
        """Generate a comprehensive meeting summary with attendee research and preparation questions"""
        try:
            # Get meeting info
            meeting_info = calendar_agent.get_meeting_by_id(event_id)
            if not meeting_info:
                return f"Meeting with ID {event_id} not found."
            
            # Research attendees
            research_results = calendar_agent.research_meeting_attendees(meeting_info)
            
            # Generate comprehensive summary
            summary = calendar_agent.generate_meeting_summary(meeting_info, research_results)
            
            return summary
            
        except Exception as e:
            return f"Error generating meeting summary: {str(e)}"

    def generate_meeting_questions(event_id: str) -> str:
        """Generate preparation questions for a meeting based on attendees and meeting type"""
        try:
            # Get meeting info
            meeting_info = calendar_agent.get_meeting_by_id(event_id)
            if not meeting_info:
                return f"Meeting with ID {event_id} not found."
            
            # Research attendees
            research_results = calendar_agent.research_meeting_attendees(meeting_info)
            
            # Generate questions
            questions = calendar_agent.generate_meeting_type_questions(meeting_info, research_results)
            
            return questions
            
        except Exception as e:
            return f"Error generating meeting questions: {str(e)}"

    def analyze_next_meeting() -> str:
        """Analyze the next upcoming meeting with attendee research and preparation suggestions"""
        try:
            summary = calendar_agent.analyze_next_meeting()
            return summary
            
        except Exception as e:
            return f"Error analyzing next meeting: {str(e)}"

    # Create StructuredTool instances
    tools = [
        StructuredTool.from_function(
            func=get_next_meeting,
            name="get_next_meeting",
            description="Get information about the next upcoming meeting from Google Calendar"
        ),
        StructuredTool.from_function(
            func=search_meetings,
            name="search_meetings", 
            description="Search for meetings by keyword in title or description. Input: keyword (string)"
        ),
        StructuredTool.from_function(
            func=get_meeting_by_id,
            name="get_meeting_by_id",
            description="Get detailed information about a specific meeting by its event ID. Input: event_id (string)"
        ),
        StructuredTool.from_function(
            func=research_person,
            name="research_person",
            description="Research a person using LinkedIn, Wikipedia, and web search. Input: name (string), context (string, optional)"
        ),
        StructuredTool.from_function(
            func=research_meeting_attendees,
            name="research_meeting_attendees",
            description="Research all attendees of a specific meeting. Input: event_id (string)"
        ),
        StructuredTool.from_function(
            func=generate_meeting_summary,
            name="generate_meeting_summary",
            description="Generate a comprehensive meeting summary with attendee research and preparation questions. Input: event_id (string)"
        ),
        StructuredTool.from_function(
            func=generate_meeting_questions,
            name="generate_meeting_questions",
            description="Generate preparation questions for a meeting based on attendees and meeting type. Input: event_id (string)"
        ),
        StructuredTool.from_function(
            func=analyze_next_meeting,
            name="analyze_next_meeting",
            description="Analyze the next upcoming meeting with attendee research and preparation suggestions"
        )
    ]
    
    return tools


class LangChainCalendarResearchAgent:
    """LangChain agent that combines calendar and person research capabilities"""
    
    def __init__(self, model: str | None = None, temperature: float = 0):
        # Store initialization parameters for lazy loading
        self.model = model
        self.temperature = temperature
        
        # Initialize LLM (this is fast)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment.")
        
        self.llm = ChatOpenAI(
            temperature=temperature,
            model=model or os.getenv("OPENAI_MODEL", "gpt-4"),
            openai_api_key=api_key,
        )
        
        # Lazy-loaded agents and tools
        self._calendar_agent = None
        self._person_agent = None
        self._tools = None
        self._agent = None
        
        print("✅ Agent initialized successfully! (Calendar services will be loaded on first use)")
    
    @property
    def calendar_agent(self):
        """Lazy load calendar agent"""
        if self._calendar_agent is None:
            print("🔄 Loading Google Calendar services...")
            self._calendar_agent = CalendarPersonResearchAgent(model=self.model, temperature=self.temperature)
            print("✅ Google Calendar services loaded!")
        return self._calendar_agent
    
    @property
    def person_agent(self):
        """Lazy load person research agent"""
        if self._person_agent is None:
            print("🔄 Loading person research services...")
            self._person_agent = UltimatePersonBioAgent(model=self.model, temperature=self.temperature)
            print("✅ Person research services loaded!")
        return self._person_agent
    
    @property
    def tools(self):
        """Lazy load tools"""
        if self._tools is None:
            print("🔄 Creating tools...")
            self._tools = create_calendar_tools(self.calendar_agent, self.person_agent)
            print("✅ Tools created!")
        return self._tools
    
    @property
    def agent(self):
        """Lazy load agent"""
        if self._agent is None:
            print("🔄 Creating LangChain agent...")
            self._agent = self._create_agent()
            print("✅ LangChain agent created!")
        return self._agent
    
    def _create_agent(self) -> AgentExecutor:
        """Create the LangChain agent with tools"""
        
        # System prompt
        system_prompt = """You are a professional meeting preparation and research assistant. You have access to Google Calendar and advanced person research capabilities.

Your capabilities include:
1. **Calendar Operations:**
   - Get information about upcoming meetings
   - Search for meetings by keyword
   - Get detailed information about specific meetings by ID

2. **Person Research:**
   - Research individuals using LinkedIn, Wikipedia, and web search
   - Research all attendees of a meeting
   - Generate comprehensive person summaries

3. **Meeting Analysis:**
   - Generate comprehensive meeting summaries with attendee research
   - Create preparation questions tailored to meeting type and attendees
   - Analyze meetings with full research and preparation suggestions

**How to help users:**
- When asked about meetings, first get the meeting information, then research attendees if needed
- Provide comprehensive analysis with both meeting details and attendee backgrounds
- Generate intelligent preparation questions based on meeting type and attendee expertise
- Always be thorough and professional in your research and analysis

**Important guidelines:**
- Always research attendees when analyzing meetings to provide valuable insights
- Generate specific, actionable preparation questions
- Provide comprehensive summaries that help users prepare effectively
- Use all available tools to give the most complete information possible"""

        # Create prompt template
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # Create agent
        agent = create_openai_tools_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )
        
        # Create agent executor
        agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=10
        )
        
        return agent_executor
    
    def run(self, query: str, chat_history: List = None) -> str:
        """Run the agent with a query"""
        if chat_history is None:
            chat_history = []
        
        try:
            result = self.agent.invoke({
                "input": query,
                "chat_history": chat_history
            })
            return result["output"]
        except Exception as e:
            return f"Error running agent: {str(e)}"
    
    def chat(self, query: str) -> str:
        """Simple chat interface"""
        return self.run(query)


def main():
    """Main function for testing the agent"""
    print("🤖 Initializing LangChain Calendar Research Agent...")
    
    try:
        agent = LangChainCalendarResearchAgent()
        print("✅ Agent initialized successfully!")
        print("\n💡 You can now ask questions like:")
        print("- 'What's my next meeting?'")
        print("- 'Research the attendees of my next meeting'")
        print("- 'Generate preparation questions for my next meeting'")
        print("- 'Search for meetings with keyword interview'")
        print("- 'Analyze meeting ID abc123'")
        print("\nType 'quit' to exit.\n")
        
        while True:
            try:
                query = input("You: ").strip()
                if query.lower() in ['quit', 'exit', 'q']:
                    break
                
                if not query:
                    continue
                
                print("\n🤖 Agent: ", end="")
                response = agent.chat(query)
                print(response)
                print("\n" + "="*60 + "\n")
                
            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")
        
    except Exception as e:
        print(f"❌ Error initializing agent: {e}")
        print("\n💡 Make sure you have:")
        print("1. Google Calendar credentials set up")
        print("2. OPENAI_API_KEY set in your environment")
        print("3. TAVILY_API_KEY set for enhanced search (optional)")


if __name__ == "__main__":
    main()
