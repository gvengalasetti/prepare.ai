#!/usr/bin/env python3
"""
Ultimate PersonBioAgent with LinkedIn, Wikipedia, and Tavily search capabilities
"""
import os
import sys
from typing import Dict, Any, List
import requests
from urllib.parse import quote_plus
import re

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

try:
    from langchain_community.tools import WikipediaQueryRun
    from langchain_community.utilities import WikipediaAPIWrapper
    HAS_WIKIPEDIA = True
except Exception:
    HAS_WIKIPEDIA = False

try:
    from langchain_community.tools.tavily_search import TavilySearchResults
    HAS_TAVILY = True
except Exception:
    HAS_TAVILY = False

load_dotenv()


class UltimatePersonBioAgent:
    """Ultimate agent with LinkedIn, Wikipedia, and Tavily search capabilities"""
    
    def __init__(self, model: str | None = None, temperature: float = 0):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment.")

        self.llm = ChatOpenAI(
            temperature=temperature,
            model=model or os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
            openai_api_key=api_key,
        )
        
        # Initialize Wikipedia tool if available
        self.wikipedia_tool = None
        if HAS_WIKIPEDIA:
            self.wikipedia_tool = WikipediaQueryRun(
                api_wrapper=WikipediaAPIWrapper(lang="en", top_k_results=3)
            )
        
        # Initialize Tavily tool if available
        self.tavily_tool = None
        if HAS_TAVILY and os.getenv("TAVILY_API_KEY"):
            self.tavily_tool = TavilySearchResults(max_results=5)
            print("✅ Tavily search enabled")
        else:
            print("ℹ️  Tavily search not available (set TAVILY_API_KEY to enable)")
        
        # LinkedIn search headers
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }

    def search_tavily(self, query: str) -> Dict[str, Any]:
        """Search using Tavily for comprehensive web results"""
        if not self.tavily_tool:
            return {'success': False, 'error': 'Tavily not available'}
        
        try:
            print(f"🔍 Tavily search: {query}")
            results = self.tavily_tool.run(query)
            
            # Extract LinkedIn profiles from Tavily results
            linkedin_profiles = []
            if isinstance(results, str):
                linkedin_urls = re.findall(r'https://[^"]*linkedin\.com/in/[^"]*', results)
                for url in linkedin_urls:
                    clean_url = re.sub(r'[?&].*', '', url)
                    linkedin_profiles.append({
                        'url': clean_url,
                        'accessible': False,
                        'method': 'tavily_search'
                    })
            
            return {
                'success': True,
                'results': results,
                'linkedin_profiles': linkedin_profiles,
                'count': len(linkedin_profiles)
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def search_linkedin(self, name: str, company: str = "") -> Dict[str, Any]:
        """Search for LinkedIn profiles using multiple strategies"""
        print(f"🔍 Searching LinkedIn for: {name}")
        
        # Strategy 1: Try direct LinkedIn URL pattern
        username = name.lower().replace(' ', '-')
        direct_url = f"https://www.linkedin.com/in/{username}"
        
        # Strategy 2: Try with company if provided
        if company:
            company_username = f"{username}-{company.lower().replace(' ', '-')}"
            company_url = f"https://www.linkedin.com/in/{company_username}"
        else:
            company_url = None
        
        # Strategy 3: Search engines
        search_queries = [
            f"linkedin.com/in/{username}",
            f"site:linkedin.com {name}",
            f"{name} linkedin profile"
        ]
        
        if company:
            search_queries.extend([
                f"site:linkedin.com {name} {company}",
                f"{name} {company} linkedin"
            ])
        
        # Test direct URLs first
        linkedin_profiles = []
        
        # Test direct URL
        try:
            response = requests.get(direct_url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                linkedin_profiles.append({
                    'url': direct_url,
                    'accessible': True,
                    'method': 'direct_url'
                })
                print(f"✅ Found direct LinkedIn profile: {direct_url}")
        except Exception as e:
            print(f"❌ Direct URL failed: {e}")
        
        # Test company URL if available
        if company_url:
            try:
                response = requests.get(company_url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    linkedin_profiles.append({
                        'url': company_url,
                        'accessible': True,
                        'method': 'company_url'
                    })
                    print(f"✅ Found company LinkedIn profile: {company_url}")
            except Exception as e:
                print(f"❌ Company URL failed: {e}")
        
        # Test search engines
        for query in search_queries:
            try:
                # Try Google search
                google_url = f"https://www.google.com/search?q={quote_plus(query)}"
                response = requests.get(google_url, headers=self.headers, timeout=10)
                
                if response.status_code == 200:
                    content = response.text
                    linkedin_urls = re.findall(r'https://[^"]*linkedin\.com/in/[^"]*', content)
                    
                    for url in linkedin_urls:
                        clean_url = re.sub(r'[?&].*', '', url)
                        if not any(p['url'] == clean_url for p in linkedin_profiles):
                            linkedin_profiles.append({
                                'url': clean_url,
                                'accessible': False,  # Will test later
                                'method': 'google_search'
                            })
                            print(f"✅ Found LinkedIn profile via Google: {clean_url}")
                            break  # Take first result
                    break  # Stop after first successful search
                    
            except Exception as e:
                print(f"❌ Google search failed: {e}")
        
        return {
            'success': len(linkedin_profiles) > 0,
            'profiles': linkedin_profiles,
            'count': len(linkedin_profiles)
        }

    def search_wikipedia(self, query: str) -> str:
        """Search Wikipedia for information about a person"""
        if not self.wikipedia_tool:
            return "Wikipedia search not available"
        
        try:
            result = self.wikipedia_tool.run(query)
            return result
        except Exception as e:
            return f"Wikipedia search error: {str(e)}"

    def summarize_person(self, name: str, description: str) -> str:
        """Research and summarize a person using all available tools"""
        
        print(f"🔍 Researching: {name}")
        print(f"📝 Description: {description}")
        print("=" * 60)
        
        # Step 1: Search LinkedIn
        linkedin_info = ""
        linkedin_profiles = []
        
        # Extract company from description if possible
        company = ""
        if "microsoft" in description.lower():
            company = "Microsoft"
        elif "apple" in description.lower():
            company = "Apple"
        elif "google" in description.lower():
            company = "Google"
        elif "tesla" in description.lower():
            company = "Tesla"
        elif "linkedin" in description.lower():
            company = "LinkedIn"
        elif "paystand" in description.lower():
            company = "Paystand"
        
        linkedin_result = self.search_linkedin(name, company)
        
        if linkedin_result['success']:
            linkedin_profiles = linkedin_result['profiles']
            linkedin_info = f"Found {linkedin_result['count']} LinkedIn profile(s):\n"
            for i, profile in enumerate(linkedin_profiles, 1):
                linkedin_info += f"{i}. {profile['url']} (via {profile['method']})\n"
        else:
            linkedin_info = "No LinkedIn profiles found"
        
        # Step 2: Search Wikipedia
        wiki_info = ""
        if self.wikipedia_tool:
            print(f"📚 Searching Wikipedia for {name}...")
            wiki_info = self.search_wikipedia(name)
            print(f"📚 Wikipedia found: {len(wiki_info)} characters of info")
        
        # Step 3: Search Tavily for additional web information
        tavily_info = ""
        if self.tavily_tool:
            print(f"🌐 Searching Tavily for {name}...")
            tavily_result = self.search_tavily(f"{name} {description}")
            if tavily_result['success']:
                tavily_info = f"Tavily search results: {tavily_result['results'][:500]}..."
                if tavily_result['linkedin_profiles']:
                    linkedin_info += f"\nAdditional LinkedIn profiles from Tavily:\n"
                    for profile in tavily_result['linkedin_profiles']:
                        linkedin_info += f"- {profile['url']}\n"
                print(f"🌐 Tavily found: {len(tavily_result['results'])} characters of info")
            else:
                tavily_info = "Tavily search not available or failed"
        else:
            tavily_info = "Tavily search not available (set TAVILY_API_KEY to enable)"
        
        # Step 4: Use LLM to synthesize information
        # IMPORTANT: Ask for strictly plain text (no Markdown) to avoid ** and other markers.
        prompt = f"""You are a professional researcher. Given the following information about a person, provide a comprehensive summary.

Person: {name}
Description/Clues: {description}

LinkedIn Information:
{linkedin_info}

Wikipedia Information:
{wiki_info if wiki_info else "No Wikipedia information available"}

Tavily Web Search Information:
{tavily_info if tavily_info else "No Tavily search information available"}

Please provide a detailed summary covering these areas (no numbering):
- Full name and current role/position
- Key achievements and notable works
- Current company/affiliation
- Brief career highlights
- LinkedIn profile links if found
- Any other relevant information from web search

CRITICAL OUTPUT REQUIREMENTS (STRICT):
- Return PLAIN TEXT only. Do NOT use Markdown symbols (no **, *, #, _, `, or >).
- Do NOT use numeric lists; use simple hyphen bullets ("- ") where helpful.
- Use short plain headings like "Summary", "Current role", etc., without numbering or punctuation.
- Avoid extra blank lines; keep spacing compact and readable.
- Keep URLs as plain text.

Format the response accordingly in plain text with consistent, clean, non-numbered headings."""

        try:
            print(f"🤖 Generating comprehensive summary...")
            response = self.llm.invoke(prompt)
            raw = response.content or ""
            return self._clean_plain_text(raw)
        except Exception as e:
            return f"Error generating summary: {str(e)}"

    def _clean_plain_text(self, text: str) -> str:
        """Sanitize LLM output to remove Markdown or odd formatting for clean UI display.

        - Strip bold/italic markers like **, __, *, _
        - Remove leading Markdown headers (#, ##, ###)
        - Normalize bullets to "- "
        - Collapse excessive blank lines
        """
        if not text:
            return ""

        # Remove markdown bold/italic and inline code/backticks
        cleaned = text
        cleaned = cleaned.replace("**", "").replace("__", "")
        cleaned = cleaned.replace("`", "")
        # Remove leftover single * or _ used as emphasis surrounding words
        import re
        cleaned = re.sub(r"\*(\S.*?)\*", r"\1", cleaned)
        cleaned = re.sub(r"_(\S.*?)_", r"\1", cleaned)
        # Remove markdown headers
        cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
        # Normalize bullets (•, *, –, numeric) to "- " at line start
        cleaned = re.sub(r"^\s*([•\-*–]|\d+[.)])\s+", "- ", cleaned, flags=re.MULTILINE)
        # Trim trailing spaces per line
        cleaned = re.sub(r"[ \t]+$", "", cleaned, flags=re.MULTILINE)
        # Collapse 3+ blank lines to max 1
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Ultimate person research with LinkedIn, Wikipedia, and Tavily")
    parser.add_argument("name", help="Person's name")
    parser.add_argument("description", help="Short description/clues", nargs="+")
    args = parser.parse_args()

    print("🤖 Initializing Ultimate PersonBioAgent...")
    
    try:
        agent = UltimatePersonBioAgent()
        print("✅ Agent initialized successfully!")
        
        summary = agent.summarize_person(args.name, " ".join(args.description))
        print(f"\n📋 Comprehensive Summary:\n{summary}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n💡 Make sure you have:")
        print("1. OPENAI_API_KEY set in your environment")
        print("2. TAVILY_API_KEY set for Tavily search (optional)")
        print("3. All required packages installed")


if __name__ == "__main__":
    main()
