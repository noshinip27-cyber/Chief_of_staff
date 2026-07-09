"""
engine.py
=========
Chief-of-Staff email engine.

Provides `fetch_threads()` which returns the most recent N inbox threads
from Gmail in a normalized shape:
    [
        {
            "thread_id": str,
            "sender":    str,
            "subject":   str,
            "snippet":   str,
            "date":      str,   # ISO-8601, e.g. "2026-06-13T12:34:56+00:00"
        },
        ...
    ]

Two execution paths are supported:

1) MCP PATH (preferred, when run inside a Cline/Claude session):
   - We document the exact MCP tool calls (`search_emails` ->
     `read_email`) and emit a structured "mcp_plan" object describing
     them. Cline (or any MCP-aware host) can execute the plan and feed
     the raw thread payloads back into `materialize_threads()`.
   - This path requires no Google credentials on disk.

2) DIRECT PATH (when run as a standalone Python script):
   - Uses the official `google-api-python-client` to hit the same
     Gmail API endpoints the MCP server wraps. Same data, just
     bypasses MCP.
   - Requires `credentials.json` (OAuth desktop client) and a
     `token.json` (auto-created on first run).
"""
from __future__ import annotations
import socket

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
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

from triage import triage_inbox, format_digest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_MAX_RESULTS = 5
GMAIL_USER_ID = "me"  # special "me" identifier for the authenticated user


# ---------------------------------------------------------------------------
# Header / metadata parsers
# ---------------------------------------------------------------------------

def _extract_sender(headers: list[dict[str, str]]) -> str:
    """Return the most useful From address from Gmail message headers."""
    for h in headers:
        if h.get("name", "").lower() == "from":
            raw = h.get("value", "").strip()
            if not raw:
                return ""
            # Prefer the bare email address when a display name is present.
            _, addr = getaddresses([raw])[0]
            if addr:
                return addr.lower()
            return raw
    return ""


def _extract_subject(headers: list[dict[str, str]]) -> str:
    for h in headers:
        if h.get("name", "").lower() == "subject":
            return h.get("value", "").strip()
    return ""


def _extract_date(headers: list[dict[str, str]]) -> str:
    """Return the message date as an ISO-8601 string (UTC)."""
    for h in headers:
        if h.get("name", "").lower() == "date":
            raw = h.get("value", "").strip()
            if not raw:
                break
            try:
                dt = parsedate_to_datetime(raw)
                if dt is None:
                    break
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                # Normalize to UTC ISO-8601 for stable downstream comparisons.
                return dt.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                break
    # Fallback: "now" in ISO-8601. We prefer a real value, but never want to
    # crash the pipeline over a missing header.
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Normalization: raw message -> thread dict
# ---------------------------------------------------------------------------

def _normalize_message(message: dict[str, Any], thread_id: str) -> dict[str, str]:
    """Convert a Gmail `users.messages.get` payload into our thread dict."""
    payload = message.get("payload", {}) or {}
    headers = payload.get("headers", []) or []

    sender = _extract_sender(headers)
    subject = _extract_subject(headers)
    date = _extract_date(headers)
    snippet = message.get("snippet", "") or ""

    return {
        "thread_id": thread_id or message.get("threadId", ""),
        "sender": sender,
        "subject": subject,
        "snippet": snippet,
        "date": date,
    }


# ---------------------------------------------------------------------------
# MCP PLAN PATH
# ---------------------------------------------------------------------------
# When fetch_threads() is invoked from inside a Cline session, we can ask the
# host to run the MCP tool calls on our behalf. The plan is a plain dict that
# describes, step-by-step, the calls the host should make.


def build_mcp_plan(max_results: int = DEFAULT_MAX_RESULTS) -> dict[str, Any]:
    """
    Return a dict describing the MCP tool calls required to fetch inbox
    threads. A Cline/Claude host can execute these and then call
    `materialize_threads()` with the results.

    The plan shape is:
        {
            "tool": "gmail",
            "steps": [
                {"tool": "search_emails",
                 "args": {"query": "in:inbox", "maxResults": 2}},
                {"tool": "read_email",
                 "args_for_each_message": True,
                 "note": "Run once per messageId from step 1."},
            ]
        }
    """
    return {
        "tool": "gmail",
        "steps": [
            {
                "tool": "search_emails",
                "args": {
                    "query": "in:inbox",
                    "maxResults": max_results,
                },
            },
            {
                "tool": "read_email",
                "args_for_each_message": True,
                "note": (
                    "Call `read_email` once per messageId returned by "
                    "step 1, then pass the full list of message objects to "
                    "engine.materialize_threads()."
                ),
            },
        ],
    }


def materialize_threads(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    Convert raw Gmail `users.messages.get` payloads (the kind `read_email`
    returns) into our normalized thread-dict list.

    Use this when `fetch_threads()` is being driven by an MCP host: feed
    in the messages you got from the `read_email` calls.
    """
    out: list[dict[str, str]] = []
    for msg in messages:
        thread_id = msg.get("threadId", "")
        out.append(_normalize_message(msg, thread_id=thread_id))
    return out


# ---------------------------------------------------------------------------
# DIRECT PATH  (google-api-python-client)
# ---------------------------------------------------------------------------
# This is what runs when you execute `python engine.py` directly. It uses
# the same Google APIs the MCP server is built on, just without the MCP
# transport layer.

def _build_gmail_service():
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    here = os.path.dirname(os.path.abspath(__file__))
    creds_path = os.path.join(here, "credentials.json")
    token_path = os.path.join(here, "token.json")

    print(f"[DEBUG] credentials path = {creds_path}")
    print(f"[DEBUG] token path       = {token_path}")

    scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/calendar",
    ]

    creds: Credentials | None = None

    if os.path.exists(token_path):
        print("[DEBUG] token.json exists")
        try:
            creds = Credentials.from_authorized_user_file(token_path, scopes)
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
                    f"Gmail OAuth client secrets not found at {creds_path}"
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                creds_path,
                scopes,
            )

            creds = flow.run_local_server(
                host="localhost",
                port=0,  # use any available port
                open_browser=True,
            )

            print("[DEBUG] OAuth completed")

        print("[DEBUG] writing token.json")

        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        print("[DEBUG] token.json written")

    print("[DEBUG] building Gmail service")

    service = build(
        "gmail",
        "v1",
        credentials=creds,
        cache_discovery=False,
    )

    print("[DEBUG] Gmail service built")

    return service

def _fetch_threads_direct(max_results: int) -> list[dict[str, str]]:
    """Direct Gmail-API implementation of `fetch_threads`."""
    service = _build_gmail_service()

    # 1) Get the most recent inbox message IDs.
    list_resp = (
        service.users()
        .messages()
        .list(
            userId=GMAIL_USER_ID,
            q="in:inbox",
            maxResults=max_results,
        )
        .execute()
    )
    message_refs = list_resp.get("messages", []) or []
    if not message_refs:
        return []

    # 2) Hydrate each message with full metadata + snippet.
    #    We request format=metadata to keep payloads small; snippet is
    #    still included in the response.
    normalized: list[dict[str, str]] = []
    for ref in message_refs:
        msg = (
            service.users()
            .messages()
            .get(
                userId=GMAIL_USER_ID,
                id=ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        normalized.append(
            _normalize_message(
                msg,
                thread_id=ref.get("threadId", ""),
            )
        )

    return normalized


# ---------------------------------------------------------------------------
# Send reply
# ---------------------------------------------------------------------------

def send_reply(
    thread_id: str,
    to: str,
    subject: str,
    body: str,
    message_id: str | None = None,
) -> dict[str, str]:
    """
    Send a reply to an existing Gmail thread.

    Parameters
    ----------
    thread_id : str
        The Gmail thread ID to attach the reply to.
    to : str
        Recipient email address.
    subject : str
        Email subject. "Re: " is prepended automatically if ``message_id``
        is provided and the subject doesn't already start with "Re: ".
    body : str
        Plain-text body of the reply.
    message_id : str | None
        The ``Message-ID`` header of the message being replied to.
        When supplied, ``In-Reply-To`` and ``References`` threading
        headers are added so mail clients thread the reply correctly.

    Returns
    -------
    dict
        ``{"message_id": str, "thread_id": str, "status": "sent"}``
    """
    import base64
    from email.mime.text import MIMEText

    # Prepend "Re: " when replying to an existing message, if not already there.
    if message_id and not subject.lower().startswith("re: "):
        subject = "Re: " + subject

    mime_msg = MIMEText(body, "plain", "utf-8")
    mime_msg["To"] = to
    mime_msg["Subject"] = subject

    # Add threading headers so mail clients group the reply correctly.
    if message_id:
        mime_msg["In-Reply-To"] = message_id
        mime_msg["References"] = message_id

    # Gmail API requires base64url encoding (no padding issues).
    raw_bytes = mime_msg.as_bytes()
    raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    service = _build_gmail_service()

    send_body: dict[str, Any] = {
        "raw": raw_b64,
        "threadId": thread_id,
    }

    sent = (
        service.users()
        .messages()
        .send(userId=GMAIL_USER_ID, body=send_body)
        .execute()
    )

    return {
        "message_id": sent.get("id", ""),
        "thread_id": sent.get("threadId", thread_id),
        "status": "sent",
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_threads(
    max_results: int = DEFAULT_MAX_RESULTS,
    *,
    use_mcp: bool | None = None,
) -> list[dict[str, str]] | dict[str, Any]:
    """
    Fetch the most recent inbox threads from Gmail.

    Returns either:
      - a list of thread dicts (the common case), OR
      - an MCP plan dict, if no Gmail credentials are available AND the
        caller hasn't already gone through the MCP path. The plan tells
        an MCP-aware host exactly which Gmail-MCP tools to invoke. Once
        the host has executed the plan, it can pass the resulting
        `read_email` payloads to `materialize_threads()` to get the
        same list of dicts back.

    Parameters
    ----------
    max_results : int
        How many inbox threads to return. Defaults to 2.
    use_mcp : bool | None
        - True  : always emit an MCP plan, never hit Google directly.
        - False : always hit Google directly, fail if creds missing.
        - None  : try direct path; fall back to MCP plan if creds are
                  not configured.
    """
    if use_mcp is True:
        return build_mcp_plan(max_results=max_results)

    if use_mcp is False:
        return _fetch_threads_direct(max_results=max_results)

    # Auto mode: try direct first, fall back to MCP plan on credential
    # errors so the function never explodes during a Cline run.
    here = os.path.dirname(os.path.abspath(__file__))
    has_creds = os.path.exists(os.path.join(here, "credentials.json")) or os.path.exists(
        os.path.join(here, "token.json")
    )
    if not has_creds:
        return build_mcp_plan(max_results=max_results)

    try:
        return _fetch_threads_direct(max_results=max_results)
    except FileNotFoundError:
        return build_mcp_plan(max_results=max_results)
    except Exception:
        import traceback

        print("\n========== FULL TRACEBACK ==========\n")
        traceback.print_exc()
        print("\n====================================\n")

        raise


# ---------------------------------------------------------------------------
# Pipeline: fetch -> triage
# ---------------------------------------------------------------------------

def run_pipeline(max_results: int = DEFAULT_MAX_RESULTS) -> None:
    """
    Fetch `max_results` inbox threads from Gmail and classify each one
    via `triage_inbox()`. Returns the prioritized list of triaged threads.
    """
    threads = fetch_threads(max_results=max_results)
    if not isinstance(threads, list):
        # MCP-plan or error dict from auto mode -> nothing to triage.
        return []
    format_digest(triage_inbox(threads))


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_pipeline(5)

# if __name__ == "__main__":
#     import json

#     result = fetch_threads()
#     if isinstance(result, list):
#         print(f"Fetched {len(result)} thread(s).")
#         for t in result:
#             print(
#                 f"- {t['date']} | {t['sender']} | {t['subject'][:60]!r}"
#             )
#         print()

#         # Classify each thread via triage.py
#         results = triage_inbox(result)
#         print(f"Triaged {len(results)} thread(s):")
#         for r in results:
#             print(
#                 f"[{r['priority'].upper()}] [{r['category']}] "
#                 f"{r['subject']} \u2014 {r['reason']}"
#             )
#         print()
#         print("Full triaged payload:")
#         print(json.dumps(results, indent=2))
#     else:
#         print("No Gmail credentials detected.")
#         print("MCP plan to execute from a Cline/Claude session:")
#         print(json.dumps(result, indent=2))
