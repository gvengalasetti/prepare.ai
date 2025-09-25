#!/usr/bin/env python3
"""
Meeting Agent Server - Chrome Extension backend for meeting prep

This mirrors enhanced_chrome_extension_server endpoints so the extension can
work the same way, and additionally exposes a general /agent-query endpoint
that uses the combined Meeting Agent (calendar + person bio tools).
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
import traceback
import sys
import os

# Workspace root on path
sys.path.append('/home/guna/Interview')

# Reuse the existing enhanced calendar capabilities for deterministic JSON
from agents.calendar_person_research_agent import CalendarPersonResearchAgent

# Combined meeting agent (tool-based) for free-form queries
from agents.meeting_agent import create_meeting_agent

app = Flask(__name__)
CORS(app)

# Initialize agents lazily
calendar_agent = None
meeting_agent = None

def ensure_calendar_agent():
    global calendar_agent
    if calendar_agent is None:
        calendar_agent = CalendarPersonResearchAgent()
    return calendar_agent

def ensure_meeting_agent():
    global meeting_agent
    if meeting_agent is None:
        meeting_agent = create_meeting_agent()
    return meeting_agent


@app.route('/health', methods=['GET'])
def health_check():
    try:
        cal_ok = True
        try:
            ensure_calendar_agent()
        except Exception:
            cal_ok = False
        meet_ok = True
        try:
            ensure_meeting_agent()
        except Exception:
            meet_ok = False
        return jsonify({
            'status': 'healthy',
            'calendar_agent_available': cal_ok,
            'meeting_agent_available': meet_ok,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/agent-query', methods=['POST'])
def agent_query():
    """Free-form query endpoint using the combined Meeting Agent."""
    try:
        data = request.get_json(force=True)
        user_input = (data or {}).get('input') or (data or {}).get('query') or ''
        if not user_input:
            return jsonify({'error': 'Missing input/query'}), 400
        agent = ensure_meeting_agent()
        result = agent.invoke({'input': user_input})
        return jsonify({'input': user_input, 'output': result.get('output')})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# The following endpoints mirror enhanced_chrome_extension_server.py so the
# Chrome extension can keep working unchanged.

@app.route('/meetings/<date_str>', methods=['GET'])
def get_meetings_for_date(date_str):
    try:
        cal = ensure_calendar_agent()
        target_date = datetime.strptime(date_str, '%Y-%m-%d')

        # Strategy 1: direct keyword search
        meetings = cal.search_meetings_by_keyword(date_str, max_results=10)

        # Strategy 2: try multiple formats if none
        if not meetings:
            date_formats = [
                target_date.strftime('%B %d, %Y'),
                target_date.strftime('%b %d, %Y'),
                target_date.strftime('%m/%d/%Y'),
                target_date.strftime('%m/%d'),
                str(target_date.day),
                target_date.strftime('%Y-%m-%d'),
            ]
            for fmt in date_formats:
                meetings = cal.search_meetings_by_keyword(fmt, max_results=10)
                if meetings:
                    break

        # Strategy 3: aggregate keywords and filter by date
        if not meetings:
            try:
                all_meetings = []
                keywords = ['meeting', 'interview', 'call', 'appointment', 'session', 'discussion', 'event']
                for kw in keywords:
                    all_meetings.extend(cal.search_meetings_by_keyword(kw, max_results=20))
                unique = []
                seen = set()
                for m in all_meetings:
                    if m.meeting_title not in seen:
                        unique.append(m)
                        seen.add(m.meeting_title)
                meetings = [m for m in unique if m.start_time and m.start_time.date() == target_date.date()]
            except Exception:
                pass

        enhanced = []
        for m in meetings:
            research = cal.research_meeting_attendees(m)
            obj = {
                'id': m.meeting_id,
                'title': m.meeting_title,
                'start_time': m.start_time.isoformat() if m.start_time else None,
                'end_time': m.end_time.isoformat() if m.end_time else None,
                'location': m.location,
                'description': m.description,
                'attendees': [],
                'research_summary': '',
                'preparation_questions': ''
            }
            for r in research:
                obj['attendees'].append({
                    'name': r.attendee.display_name,
                    'email': r.attendee.email,
                    'company': r.attendee.company,
                    'title': r.attendee.title,
                    'research_summary': r.research_summary,
                    'found_info': r.found_info,
                })
            try:
                obj['research_summary'] = cal.generate_meeting_summary(m, research)
                obj['preparation_questions'] = cal.generate_meeting_type_questions(m, research)
            except Exception:
                obj['research_summary'] = 'Error generating research summary'
                obj['preparation_questions'] = 'Error generating preparation questions'
            enhanced.append(obj)

        return jsonify({'date': date_str, 'meetings': enhanced, 'count': len(enhanced)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e), 'meetings': []}), 500


@app.route('/meeting/<meeting_id>', methods=['GET'])
def get_meeting_details(meeting_id):
    try:
        cal = ensure_calendar_agent()
        meeting = cal.get_meeting_by_id(meeting_id)
        if not meeting:
            return jsonify({'error': 'Meeting not found'}), 404
        research = cal.research_meeting_attendees(meeting)
        meeting_summary = cal.generate_meeting_summary(meeting, research)
        preparation_questions = cal.generate_meeting_type_questions(meeting, research)
        obj = {
            'id': meeting.meeting_id,
            'title': meeting.meeting_title,
            'start_time': meeting.start_time.isoformat() if meeting.start_time else None,
            'end_time': meeting.end_time.isoformat() if meeting.end_time else None,
            'location': meeting.location,
            'description': meeting.description,
            'attendees': [],
            'research_summary': meeting_summary,
            'preparation_questions': preparation_questions,
        }
        for r in research:
            obj['attendees'].append({
                'name': r.attendee.display_name,
                'email': r.attendee.email,
                'company': r.attendee.company,
                'title': r.attendee.title,
                'research_summary': r.research_summary,
                'found_info': r.found_info,
            })
        return jsonify(obj)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/next-meeting', methods=['GET'])
def next_meeting():
    try:
        cal = ensure_calendar_agent()
        meeting = cal.get_next_meeting_info()
        if not meeting:
            return jsonify({'message': 'No upcoming meetings found', 'meeting': None})
        research = cal.research_meeting_attendees(meeting)
        meeting_summary = cal.generate_meeting_summary(meeting, research)
        preparation_questions = cal.generate_meeting_type_questions(meeting, research)
        obj = {
            'id': meeting.meeting_id,
            'title': meeting.meeting_title,
            'start_time': meeting.start_time.isoformat() if meeting.start_time else None,
            'end_time': meeting.end_time.isoformat() if meeting.end_time else None,
            'location': meeting.location,
            'description': meeting.description,
            'attendees': [],
            'research_summary': meeting_summary,
            'preparation_questions': preparation_questions,
        }
        for r in research:
            obj['attendees'].append({
                'name': r.attendee.display_name,
                'email': r.attendee.email,
                'company': r.attendee.company,
                'title': r.attendee.title,
                'research_summary': r.research_summary,
                'found_info': r.found_info,
            })
        return jsonify({'meeting': obj})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/search-meetings', methods=['POST'])
def search_meetings_endpoint():
    try:
        cal = ensure_calendar_agent()
        data = request.get_json(force=True)
        keyword = (data or {}).get('keyword', '').strip()
        if not keyword:
            return jsonify({'error': 'Keyword is required'}), 400
        meetings = cal.search_meetings_by_keyword(keyword, max_results=5)
        enhanced = []
        for m in meetings:
            research = cal.research_meeting_attendees(m)
            obj = {
                'id': m.meeting_id,
                'title': m.meeting_title,
                'start_time': m.start_time.isoformat() if m.start_time else None,
                'end_time': m.end_time.isoformat() if m.end_time else None,
                'location': m.location,
                'description': m.description,
                'attendees': [],
                'research_summary': '',
                'preparation_questions': ''
            }
            for r in research:
                obj['attendees'].append({
                    'name': r.attendee.display_name,
                    'email': r.attendee.email,
                    'company': r.attendee.company,
                    'title': r.attendee.title,
                    'research_summary': r.research_summary,
                    'found_info': r.found_info,
                })
            try:
                obj['research_summary'] = cal.generate_meeting_summary(m, research)
                obj['preparation_questions'] = cal.generate_meeting_type_questions(m, research)
            except Exception:
                obj['research_summary'] = 'Error generating research summary'
                obj['preparation_questions'] = 'Error generating preparation questions'
            enhanced.append(obj)
        return jsonify({'keyword': keyword, 'meetings': enhanced, 'count': len(enhanced)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("🚀 Starting Meeting Agent Server...")
    print("🤝 Combining calendar search + person bio tools")
    print("🌐 Server at http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)


