#!/usr/bin/env python3
"""
Meeting Agent - combines calendar search tools and person bio tools.

Reuses existing @tool functions so that the agent can:
 - query meetings (next meeting, search by keyword, events by day, etc.)
 - research people (research summary, LinkedIn, Wikipedia, Tavily)

Factory: create_meeting_agent()
"""

import os
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate

# Import tool functions from existing agents
from calendar_search_agent import (
    get_next_meeting,
    search_meetings,
    get_meeting_by_id,
    get_day_events,
    extract_meeting_description,
    get_attendees_for_day,
)
from agents.person_bio_search_agent import (
    research_person,
    search_linkedin,
    search_wikipedia,
    search_tavily,
)

load_dotenv()


def create_meeting_agent():
    """Create and return a LangChain agent combining calendar + person tools."""
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found. Set it in environment or .env")

    llm = ChatOpenAI(
        model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
        temperature=0,
        api_key=api_key
    )

    tools = [
        # Calendar tools
        get_next_meeting,
        search_meetings,
        get_meeting_by_id,
        get_day_events,
        extract_meeting_description,
        get_attendees_for_day,
        # Person research tools
        research_person,
        search_linkedin,
        search_wikipedia,
        search_tavily,
    ]

    prompt = PromptTemplate(
        input_variables=["tools", "tool_names", "input", "agent_scratchpad"],
        template="""You are Meeting Agent: a meeting prep assistant that can look up calendar events and research attendees.

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

Guidance:
- For meeting queries, use calendar tools to fetch details, then (if names are present) use person tools to research attendees.
- Keep results concise and actionable, with bullet points for attendees and suggested prep questions when relevant.

Begin!

Question: {input}
Thought: {agent_scratchpad}"""
    )

    agent = create_react_agent(llm, tools, prompt)
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=6,
    )
    return executor


