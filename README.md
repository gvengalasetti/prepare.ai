Paystand Trial AI Project: Prepare.Ai
Problem Statement:
As a student, and in my professional experiences, I have found that there is a bombardment of meetings, events, and opportunities that present themselves to you. Whether it be hackathons, seminars, networking or even meetings with senior engineers, to really make the most of these experiences, preparation is key. 
It's important to know you’ll be speaking to and being ready going into meetings and networking opportunities. And so Prepare.ai “Smarter Meeting Preparation & Networking with AI” is born–A tool that surfaces attendee backgrounds and helps you craft sharp, relevant questions.
Github Repo:
https://github.com/gvengalasetti/meetingagent 
My Experiences:
Approach
	Right off the bat, the meeting preparation problem had been marinating in the back of my brain, and this exercise gave me the opportunity to try and solve it. I knew that for a problem like this, the point is to make the preparation process convenient. Secondly, in brainstorming ideas I felt it would be a good use case for an AI agent. The process of meeting prep can involve a workflow with a variety of decisions that are simple enough to be automated. 
Where & How AI Was Used
Key AI Uses:
To brainstorm new and flesh out existing ideas
To troubleshoot
To build off code and documentation I set up
To write tests for functions
Using LLM’s in methods for text summarization and other NLP 

	It’s important when using AI tools to understand that they are tools merely, and that they can speed up your workflow, but it has to be used with intent. I have found allowing the LLM’s to drive your decisions, can start to cause problems as the project grows in complexity. 
One trick I like to use is to take advantage of the context and give the agent examples of what a method should look like. Using documentation from a good resource can be really efficient in producing better code. This focuses the LLM in a more structured manner.
Challenges & How I Solved Them
Key Challenges:
To brainstorm new and flesh out existing ideas
To troubleshoot
To build off code and documentation I set up
To write tests for functions
Using LLM’s in methods for text summarization and other NLP 

Choosing the platform.
 I first considered a simple web app, but a Chrome extension fit the use case better. I’d never built one before, so I treated it as a chance to learn.
Selecting the agent framework.
 I chose LangChain because it’s a large open-source agent framework with strong community support. Although I’ve primarily worked with AWS and experimented a bit with CrewAI, this was a good opportunity to try LangChain. The key idea was to lean on tools: write modular code that exposes API calls the agent can invoke when needed.
Meeting search agent & People research agent.
 I began with an agent that retrieves meetings from my calendar. Because this is a personal project, I set up OAuth and connected to Google APIs. After running into limitations with Calendar alone, I added Google Contacts and Gmail so the agent could resolve names more reliably. —I then integrated a second agent to search a variety of internet sources for background on each person, using the original meeting context. It queries LinkedIn, Google, Wikipedia, and Tavily, and the UI shows source icons.
Combining agents & prompting.
 I then composed the two agents. The main lessons: apply discretion, use short and precise prompts, and break instructions into smaller steps so the LLM is less likely to drift.

Demo:
https://drive.google.com/file/d/1Ug5j5MSI5Lpm2uPAjbjY-Wvwr2vqus00/view?usp=sharing 



