#!/usr/bin/env python3
"""
Calendar Search Agent - LangChain Agent for Calendar Information
This agent can search and extract information from Google Calendar using various tools.
"""

import os
from typing import Any, Dict, List
from dotenv import load_dotenv

from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.tools import tool

# Import the calendar agent
from calendar_agent import CalendarAgent

# Load environment variables
load_dotenv()

@tool
def get_next_meeting(_: str = "") -> str:
    """Get information about the next upcoming meeting."""
    try:
        agent = CalendarAgent()
        meeting = agent.get_next_meeting_info()
        
        if not meeting:
            return "No upcoming meetings found."
        
        result = f"Next Meeting: {meeting.meeting_title}\n"
        result += f"Start Time: {meeting.start_time}\n"
        result += f"End Time: {meeting.end_time}\n"
        result += f"Location: {meeting.location}\n"
        result += f"Description: {meeting.original_description}\n"
        result += f"Meeting ID: {meeting.meeting_id}\n"
        
        if meeting.attendees:
            result += f"Attendees: {', '.join(meeting.get_attendee_display_names())}\n"
            result += f"Attendee Emails: {', '.join(meeting.get_attendee_emails())}\n"
        
        if meeting.organizer_name:
            result += f"Organizer: {meeting.organizer_name} ({meeting.organizer_email})\n"
        
        return result
        
    except Exception as e:
        return f"Error getting next meeting: {str(e)}"

@tool
def search_meetings(keyword: str) -> str:
    """Search for meetings by keyword in title or description."""
    try:
        agent = CalendarAgent()
        meetings = agent.search_meetings_by_keyword(keyword, max_results=5)
        
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
                result += f"   Attendees: {', '.join(meeting.get_attendee_display_names())}\n"
            result += "\n"
        
        return result
        
    except Exception as e:
        return f"Error searching meetings: {str(e)}"

@tool
def get_meeting_by_id(event_id: str) -> str:
    """Get detailed information about a specific meeting by its event ID."""
    try:
        agent = CalendarAgent()
        meeting = agent.get_meeting_info_by_id(event_id)
        
        if not meeting:
            return f"Meeting with ID {event_id} not found."
        
        result = f"Meeting: {meeting.meeting_title}\n"
        result += f"Start Time: {meeting.start_time}\n"
        result += f"End Time: {meeting.end_time}\n"
        result += f"Location: {meeting.location}\n"
        result += f"Description: {meeting.original_description}\n"
        result += f"Meeting ID: {meeting.meeting_id}\n"
        
        if meeting.attendees:
            result += f"Attendees: {', '.join(meeting.get_attendee_display_names())}\n"
            result += f"Attendee Emails: {', '.join(meeting.get_attendee_emails())}\n"
        
        if meeting.organizer_name:
            result += f"Organizer: {meeting.organizer_name} ({meeting.organizer_email})\n"
        
        return result
        
    except Exception as e:
        return f"Error getting meeting by ID: {str(e)}"

@tool
def get_day_events(date_input: str) -> str:
    """Get all events for a specific day. Input format: YYYY-MM-DD (e.g., '2024-01-15')."""
    try:
        # Normalize input (strip quotes/whitespace)
        normalized_date = date_input.strip().strip('"\'')
        agent = CalendarAgent()
        day_events = agent.get_events_for_day(normalized_date)
        
        if day_events.total_events == 0:
            return f"No events found for {normalized_date}"
        
        # Compute total_attendees if attribute not present
        total_attendees = getattr(day_events, 'total_attendees', None)
        if total_attendees is None and hasattr(day_events, 'events'):
            try:
                total_attendees = sum(len(getattr(e, 'attendees', []) or []) for e in day_events.events)
            except Exception:
                total_attendees = 0
        
        result = f"Events for {normalized_date}:\n"
        result += f"Total Events: {day_events.total_events}\n"
        if total_attendees is not None:
            result += f"Total Attendees: {total_attendees}\n\n"
        else:
            result += "\n"
        
        for i, event in enumerate(day_events.events, 1):
            result += f"{i}. {event.meeting_title}\n"
            result += f"   Time: {event.start_time} - {event.end_time}\n"
            result += f"   Location: {event.location}\n"
            if event.attendees:
                result += f"   Attendees: {', '.join(event.get_attendee_display_names())}\n"
            result += "\n"
        
        return result
        
    except Exception as e:
        return f"Error getting day events: {str(e)}"

@tool
def extract_meeting_description(meeting_id: str) -> str:
    """Extract detailed information from a meeting's description using AI."""
    try:
        agent = CalendarAgent()
        description_info = agent.extract_description_info(meeting_id)
        
        if not description_info:
            return f"No description information found for meeting {meeting_id}"
        
        result = f"Description Analysis for Meeting {meeting_id}:\n"
        result += f"Title: {description_info.get('title', 'N/A')}\n"
        result += f"Key Points: {description_info.get('key_points', 'N/A')}\n"
        result += f"Action Items: {description_info.get('action_items', 'N/A')}\n"
        result += f"Participants: {description_info.get('participants', 'N/A')}\n"
        result += f"Meeting Type: {description_info.get('meeting_type', 'N/A')}\n"
        
        return result
        
    except Exception as e:
        return f"Error extracting description: {str(e)}"

@tool
def get_attendees_for_day(date_input: str) -> str:
    """Get attendee information for all meetings in a day. Input format: YYYY-MM-DD (e.g., '2024-01-15')."""
    try:
        # Normalize input (strip quotes/whitespace)
        normalized_date = date_input.strip().strip('"\'')
        agent = CalendarAgent()
        attendee_info = agent.get_attendee_info_for_day(normalized_date)
        
        if not attendee_info:
            return f"No attendee information found for {normalized_date}"
        
        result = f"Attendee Information for {normalized_date}:\n"
        result += f"Total Unique Attendees: {attendee_info.get('total_unique_attendees', 0)}\n"
        result += f"Total Meetings: {attendee_info.get('total_meetings', 0)}\n\n"
        
        # List all attendees
        all_attendees = attendee_info.get('all_attendees', [])
        if all_attendees:
            result += "All Attendees:\n"
            for attendee in all_attendees:
                result += f"- {attendee.get('name', 'Unknown')} ({attendee.get('email', 'No email')})\n"
        
        # Meeting details
        meeting_details = attendee_info.get('meeting_details', [])
        if meeting_details:
            result += "\nMeeting Details:\n"
            for meeting in meeting_details:
                result += f"- {meeting.get('title', 'No title')}\n"
                result += f"  Attendees: {', '.join(meeting.get('attendees', []))}\n"
        
        return result
        
    except Exception as e:
        return f"Error getting attendees for day: {str(e)}"

def create_calendar_search_agent():
    """Create and return a LangChain agent with calendar search tools."""
    
    # Check for OpenAI API key
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found. Please set your OpenAI API key in the environment or .env file")
    
    # Initialize the LLM
    llm = ChatOpenAI(
        model="gpt-3.5-turbo",
        temperature=0,
        api_key=api_key
    )
    
    # Define tools using the @tool decorator functions
    tools = [
        get_next_meeting,
        search_meetings,
        get_meeting_by_id,
        get_day_events,
        extract_meeting_description,
        get_attendees_for_day
    ]
    
    # Create prompt template
    prompt = PromptTemplate(
        input_variables=["tools", "tool_names", "input", "agent_scratchpad"],
        template="""You are a helpful calendar assistant that can search and extract information from Google Calendar.

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

Begin!

Question: {input}
Thought: {agent_scratchpad}"""
    )
    
    # Create the agent
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

# This module intentionally exposes only tools and the agent factory.
