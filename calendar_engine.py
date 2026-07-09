"""
calendar_engine.py
==================
Chief-of-Staff Google Calendar engine.

Provides `_build_calendar_service()` which returns an authenticated
Google Calendar API v3 service object.

OAuth details
-------------
- Shares the same credentials.json and token.json as engine.py.
- Uses the same three scopes so a single token covers both Gmail and Calendar:
    * https://www.googleapis.com/auth/gmail.readonly
    * https://www.googleapis.com/auth/gmail.send
    * https://www.googleapis.com/auth/calendar
- If token.json does not exist or has expired, the standard
  InstalledAppFlow OAuth browser flow is triggered automatically.
"""
from __future__ import annotations
import socket

# ---------------------------------------------------------------------------
# IPv4 monkey-patch (mirrors engine.py)
# Prevents getaddrinfo from returning IPv6 addresses, which can cause
# connection failures on some Windows/WSL setups.
# ---------------------------------------------------------------------------
_original_getaddrinfo = socket.getaddrinfo


def ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(
        host,
        port,
        socket.AF_INET,  # Force IPv4
        type,
        proto,
        flags,
    )


socket.getaddrinfo = ipv4_only_getaddrinfo

import os
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
_gemini_model = genai.GenerativeModel("gemini-2.5-flash")


# ---------------------------------------------------------------------------
# Shared OAuth scopes
# Must stay in sync with engine.py so both modules share one token.json.
# ---------------------------------------------------------------------------
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


# ---------------------------------------------------------------------------
# Service builder
# ---------------------------------------------------------------------------

def _build_calendar_service():
    """
    Build and return an authenticated Google Calendar API v3 service.

    Uses the same credentials.json / token.json as engine.py so the user
    only ever goes through the OAuth flow once for the whole project.

    Returns
    -------
    googleapiclient.discovery.Resource
        An authenticated Calendar v3 service ready for API calls.
    """
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    here = os.path.dirname(os.path.abspath(__file__))
    creds_path = os.path.join(here, "credentials.json")
    token_path = os.path.join(here, "token.json")

    print(f"[DEBUG] credentials path = {creds_path}")
    print(f"[DEBUG] token path       = {token_path}")

    creds: Credentials | None = None

    if os.path.exists(token_path):
        print("[DEBUG] token.json exists")
        try:
            creds = Credentials.from_authorized_user_file(token_path, _SCOPES)
            print("[DEBUG] loaded token.json")
        except ValueError as e:
            print(f"[DEBUG] token invalid: {e}")
            creds = None

    if not creds or not creds.valid:
        print("[DEBUG] need authentication")

        if creds and creds.expired and creds.refresh_token:
            print("[DEBUG] refreshing token")
            creds.refresh(Request())
            print("[DEBUG] token refreshed")

        else:
            print("[DEBUG] starting OAuth flow")

            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"OAuth client secrets not found at {creds_path}"
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                creds_path,
                _SCOPES,
            )

            creds = flow.run_local_server(
                host="localhost",
                port=0,  # let the OS pick any free port
                open_browser=True,
            )

            print("[DEBUG] OAuth completed")

        print("[DEBUG] writing token.json")

        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        print("[DEBUG] token.json written")

    print("[DEBUG] building Calendar service")

    service = build(
        "calendar",
        "v3",
        credentials=creds,
        cache_discovery=False,
    )

    print("[DEBUG] Calendar service built")

    return service

# ---------------------------------------------------------------------------
# Meeting request parser
# ---------------------------------------------------------------------------

def parse_meeting_request(thread: dict[str, Any]) -> dict[str, Any]:
    """
    Extract meeting details from an email thread using Gemini.

    Uses gemini-2.5-flash to parse the thread messages and extract:
      - proposed_times: list of ISO-8601 datetime strings
      - attendees: list of email addresses
      - topic: one-line summary of the meeting purpose
      - duration_minutes: integer, default 30

    Parameters
    ----------
    thread : dict
        Thread dict in the UI shape with "messages" list. Each message
        has "from", "date", and "body" keys.

    Returns
    -------
    dict
        On success: {"proposed_times": [...], "attendees": [...],
                     "topic": "...", "duration_minutes": 30}
        On failure: {"parsing_error": "<error message>"}
    """
    import json
    from datetime import datetime

    # Concatenate all messages in the thread
    messages = thread.get("messages") or []
    if not messages:
        return {"parsing_error": "Thread has no messages"}

    subject = thread.get("subject", "")
    conversation = []

    # Include the thread subject as a header so Gemini has full context
    if subject:
        conversation.append(f"Subject: {subject}")

    for i, msg in enumerate(messages, start=1):
        sender = msg.get("from", "Unknown")
        date = msg.get("date", "")
        body = msg.get("body", "")
        conversation.append(f"Message {i} — From: {sender} · {date}\n{body}")

    concatenated = "\n\n---\n\n".join(conversation)

    # Build prompt with today's date for relative day resolution
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""
You are an assistant parsing meeting requests from email threads.

Today's date: {today}
The user's timezone is IST (India Standard Time, UTC+5:30).
Use it to resolve any relative day references(example:this friday, next monday)


Email thread:

{concatenated}

Extract the following meeting details from the thread. If information is not explicitly stated, use reasonable defaults.

Return ONLY valid JSON with this exact schema:
{{
  "proposed_times": ["<ISO-8601 datetime>", ...],
  "attendees": ["<email>", ...],
  "topic": "<one-line summary>",
  "duration_minutes": <integer, default 30>
}}

Rules:
- proposed_times: Convert any mentioned date/time to ISO-8601 format (YYYY-MM-DDTHH:MM:SS+05:30) in IST (India Standard Time, UTC+5:30). Use today's date ({today}) as the base for resolving relative day names like "tomorrow", "next Monday", etc. Always include the +05:30 offset in the output.
- attendees: Extract all email addresses mentioned in From/To/Cc, plus any emails in the message body.
- topic: A concise one-line summary of what the meeting is about.
- duration_minutes: If a duration is mentioned, use it. Otherwise default to 30.
-Do not add any other keys or exlanations

If the thread is not a meeting request, return the JSON anyway with empty/default values.
"""

    try:
        # Call Gemini with JSON response type
        response = _gemini_model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )

        raw_text = response.text.strip()

        # Strip markdown code fences if present (```json ... ```)
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            # Remove first line if it's ```json or ```
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Remove last line if it's ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()

        # Parse JSON
        parsed = json.loads(raw_text)

        # Validate expected keys
        if not isinstance(parsed, dict):
            return {"parsing_error": "Gemini returned non-dict JSON"}

        # Ensure all keys exist with defaults
        result = {
            "proposed_times": parsed.get("proposed_times", []),
            "attendees": parsed.get("attendees", []),
            "topic": parsed.get("topic", "Meeting"),
            "duration_minutes": parsed.get("duration_minutes", 30),
        }

        return result

    except json.JSONDecodeError as e:
        return {"parsing_error": f"Failed to parse JSON from Gemini: {e}"}
    except Exception as e:
        return {"parsing_error": f"Gemini API call failed: {e}"}


# ---------------------------------------------------------------------------
# Availability checker
# ---------------------------------------------------------------------------

def check_availability(time_min: str, time_max: str) -> bool:
    """
    Check whether the user's primary calendar is free between two times.

    Calls the Calendar FreeBusy API and returns True if the slot is free,
    False if there is at least one conflicting event — or if anything goes
    wrong (safe default: assume busy so we never double-book).

    Parameters
    ----------
    time_min : str
        Start of the window in ISO-8601. A bare datetime without timezone
        info (e.g. "2026-07-09T14:00:00") gets "Z" appended automatically.
    time_max : str
        End of the window, same rules as time_min.

    Returns
    -------
    bool
        True = free, False = busy / error.
    """
    try:
        # Append IST offset (+05:30) when no timezone info is present
        # (bare datetime strings like "2026-07-10T16:00:00" are IST)
        if time_min and "+" not in time_min and not time_min.endswith("Z"):
            time_min = time_min + "+05:30"
        if time_max and "+" not in time_max and not time_max.endswith("Z"):
            time_max = time_max + "+05:30"

        print(f"[check_availability] FreeBusy query: {time_min} → {time_max}")
        service = _build_calendar_service()

        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}],
        }

        response = service.freebusy().query(body=body).execute()

        # busy is a list of {start, end} dicts; empty list means free
        busy_slots = (
            response.get("calendars", {})
            .get("primary", {})
            .get("busy", [])
        )

        print(f"[check_availability] Busy slots returned: {busy_slots}")
        return len(busy_slots) == 0

    except Exception as e:
        print(f"[check_availability] Exception: {e}")
        raise  # surface the real error instead of silently returning False


# ---------------------------------------------------------------------------
# Free slot finder
# ---------------------------------------------------------------------------

def find_free_slot(
    proposed_times: list[str],
    duration_minutes: int = 30,
) -> str | None:
    """
    Return the first proposed time at which the user's calendar is free.

    Iterates through proposed_times in order, computes the end time by
    adding duration_minutes, calls check_availability for each, and
    returns the first free start time string. Malformed time strings are
    skipped gracefully.

    Parameters
    ----------
    proposed_times : list[str]
        ISO-8601 datetime strings (e.g. from parse_meeting_request).
    duration_minutes : int
        Length of the meeting in minutes. Defaults to 30.

    Returns
    -------
    str | None
        The first free start time as an ISO-8601 string, or None if no
        proposed slot is available.
    """
    from datetime import datetime, timedelta, timezone

    IST = timezone(timedelta(hours=5, minutes=30))

    for time_str in proposed_times:
        try:
            time_str = time_str.strip()

            # Normalise: treat bare datetime strings (no tz info) as IST
            normalized = time_str.replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(normalized)

            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=IST)
            else:
                start_dt = start_dt.astimezone(IST)

            end_dt = start_dt + timedelta(minutes=duration_minutes)

            # Always pass explicit IST offset strings to check_availability
            time_min = start_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
            time_max = end_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")

            print(f"[find_free_slot] Checking {time_min} → {time_max}")
            available = check_availability(time_min, time_max)
            print(f"[find_free_slot] Available: {available}")

            if available:
                # Return as an explicit IST string so create_event gets
                # an unambiguous timezone-aware value
                return start_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")

        except (ValueError, TypeError) as e:
            print(f"[find_free_slot] Skipping malformed time '{time_str}': {e}")
            continue

    return None  # no free slot found among the proposed times


# ---------------------------------------------------------------------------
# Event creator
# ---------------------------------------------------------------------------

def create_event(
    summary: str,
    start_time: str,
    duration_minutes: int = 30,
    attendees: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    """
    Create a Google Calendar event on the user's primary calendar.

    Parameters
    ----------
    summary : str
        Title of the calendar event.
    start_time : str
        ISO-8601 datetime string for the event start (e.g. "2026-07-09T14:00:00"
        or "2026-07-09T14:00:00Z").
    duration_minutes : int
        Length of the meeting in minutes. Defaults to 30.
    attendees : list[str] | None
        Email addresses to invite. Strings without "@" are silently
        filtered out. Pass None or [] to create an event with no attendees.
    description : str
        Optional body text for the event (e.g. the approved draft reply).

    Returns
    -------
    dict
        The full event resource dict returned by the Calendar API,
        including the generated event id, htmlLink, etc.
    """
    from datetime import datetime, timedelta, timezone

    IST = timezone(timedelta(hours=5, minutes=30))

    # --- Calculate end time ---
    # Normalize the start time string so fromisoformat() can parse it.
    normalized_start = start_time.strip().replace("Z", "+00:00")
    start_dt = datetime.fromisoformat(normalized_start)

    # If the parsed datetime has no timezone, treat it as IST
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=IST)
    else:
        # Convert to IST so the calendar event shows the correct local time
        start_dt = start_dt.astimezone(IST)

    end_dt = start_dt + timedelta(minutes=duration_minutes)

    # Format as local IST datetime strings (no UTC conversion)
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    end_str   = end_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")

    # --- Build event body ---
    event_body: dict[str, Any] = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_str,
            "timeZone": "Asia/Kolkata",
        },
        "end": {
            "dateTime": end_str,
            "timeZone": "Asia/Kolkata",
        },
    }

    # --- Attendees — only include valid email addresses ---
    if attendees:
        valid = [
            {"email": addr.strip()}
            for addr in attendees
            if isinstance(addr, str) and "@" in addr
        ]
        if valid:
            event_body["attendees"] = valid

    # --- Call the API ---
    service = _build_calendar_service()

    created = (
        service.events()
        .insert(
            calendarId="primary",
            body=event_body,
            sendUpdates="all",   # sends invitation emails to all attendees
        )
        .execute()
    )

    return created
