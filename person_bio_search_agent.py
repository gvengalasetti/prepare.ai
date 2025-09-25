#!/usr/bin/env python3
"""
Person Bio Search Agent - wraps UltimatePersonBioAgent as LangChain tools.

Tools exposed via @tool for robust function-calling:
 - research_person(name, context)
 - search_linkedin(name, company)
 - search_wikipedia(query)
 - search_tavily(query)
"""

import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain.tools import tool

from agents.ultimate_person_bio_agent import UltimatePersonBioAgent

load_dotenv()


def _get_agent() -> UltimatePersonBioAgent:
    return UltimatePersonBioAgent()


@tool
def research_person(name_and_context: str) -> str:
    """Research a person using LinkedIn, Wikipedia, and web search. Input format: 'Name | optional context'"""
    try:
        parts = [p.strip() for p in name_and_context.split('|', 1)]
        name = parts[0] if parts and parts[0] else name_and_context.strip()
        context = parts[1] if len(parts) > 1 else ""
        agent = _get_agent()
        return agent.summarize_person(name, context)
    except Exception as e:
        return f"Error: {e}"


@tool
def search_linkedin(input_str: str) -> str:
    """Search LinkedIn profiles. Input format: 'Name | optional company'"""
    try:
        parts = [p.strip() for p in input_str.split('|', 1)]
        name = parts[0]
        company = parts[1] if len(parts) > 1 else ""
        agent = _get_agent()
        res = agent.search_linkedin(name, company)
        if not res.get('success'):
            return "No LinkedIn profiles found"
        profiles = res.get('profiles', [])
        lines = [f"Found {len(profiles)} LinkedIn profile(s):"]
        for p in profiles:
            lines.append(f"- {p.get('url')} (via {p.get('method')})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool
def search_wikipedia(query: str) -> str:
    """Search Wikipedia for information about a person. Input: query string."""
    try:
        agent = _get_agent()
        return agent.search_wikipedia(query)
    except Exception as e:
        return f"Error: {e}"


@tool
def search_tavily(query: str) -> str:
    """Search Tavily for comprehensive web results (requires TAVILY_API_KEY). Input: query string."""
    try:
        agent = _get_agent()
        res = agent.search_tavily(query)
        if not res.get('success'):
            return f"Tavily search failed: {res.get('error', 'unknown error')}"
        out = ["Tavily search succeeded"]
        linkedin = res.get('linkedin_profiles') or []
        if linkedin:
            out.append("LinkedIn profiles:")
            for p in linkedin:
                out.append(f"- {p.get('url')}")
        return "\n".join(out)
    except Exception as e:
        return f"Error: {e}"


def create_person_bio_agent():
    """Create and return a LangChain agent with person bio tools."""
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found. Set it in environment or .env")

    llm = ChatOpenAI(
        model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
        temperature=0,
        api_key=api_key
    )

    tools = [
        research_person,
        search_linkedin,
        search_wikipedia,
        search_tavily,
    ]

    prompt = PromptTemplate(
        input_variables=["tools", "tool_names", "input", "agent_scratchpad"],
        template="""You are a helpful person research assistant.

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

    agent = create_react_agent(llm, tools, prompt)
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=5,
    )
    return executor


