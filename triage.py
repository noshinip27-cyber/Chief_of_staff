import os
import time
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash-lite")

def triage_thread(sender: str, subject: str, snippet: str) -> dict:
    prompt = f"""
        You are an intelligent email assistant helping triage an inbox.

        Given this email thread metadata, classify it:

        Sender: {sender}
        Subject: {subject}
        Preview: {snippet}

        Respond in this exact format:
        Priority: <urgent | needs-reply | fyi | ignore>
        Category: <one short tag like: meeting-request, follow-up, newsletter, billing, job-app, social, admin, other>
        Reason: <one sentence explaining why>
        """

    response = model.generate_content(prompt)

    return parse_triage_response(response.text)


def parse_triage_response(text: str) -> dict:
    result = {"priority": "unknown", "category": "other", "reason": ""}

    for line in text.strip().split("\n"):
        if line.startswith("Priority:"):
            result["priority"] = line.replace("Priority:", "").strip().lower()
        elif line.startswith("Category:"):
            result["category"] = line.replace("Category:", "").strip().lower()
        elif line.startswith("Reason:"):
            result["reason"] = line.replace("Reason:", "").strip()

    return result

def triage_inbox(threads: list) -> list:
    import json
    if not threads:
        return []

    triaged = []

    try:
        # Prepare the threads representation for batching
        batch_input = []
        for idx, thread in enumerate(threads):
            batch_input.append({
                "index": idx,
                "sender": thread.get("sender", ""),
                "subject": thread.get("subject", ""),
                "snippet": thread.get("snippet", "")
            })

        prompt = f"""
        You are an intelligent email assistant helping triage an inbox.

        Given the following list of email threads as a JSON array, classify each one:

        {json.dumps(batch_input, indent=2)}

        For each thread, determine:
        1. Priority: Must be one of 'urgent', 'needs-reply', 'fyi', or 'ignore'.
        2. Category: A short tag like: 'meeting-request', 'follow-up', 'newsletter', 'billing', 'job-app', 'social', 'admin', or 'other'.
        3. Reason: A single sentence explaining why.

        Respond in JSON format as a list of objects matching this schema:
        [
            {{
                "index": <integer matching the input thread index>,
                "priority": "<urgent | needs-reply | fyi | ignore>",
                "category": "<category>",
                "reason": "<explanation>"
            }},
            ...
        ]
        """

        # Configure model to return JSON
        for attempt in range(3):
            try:
                response = model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                break
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower()) and attempt < 2:
                    wait = 15 * (2 ** attempt)
                    print(f"[triage] Rate limit hit — waiting {wait}s before retry {attempt + 2}/3…")
                    time.sleep(wait)
                    continue
                raise

        raw_results = json.loads(response.text)

        # Map the results back to the original threads
        results_map = {}
        for item in raw_results:
            if isinstance(item, dict) and "index" in item:
                results_map[int(item["index"])] = {
                    "priority": item.get("priority", "unknown").strip().lower(),
                    "category": item.get("category", "other").strip().lower(),
                    "reason": item.get("reason", "").strip()
                }

        for idx, thread in enumerate(threads):
            label = results_map.get(idx, {"priority": "unknown", "category": "other", "reason": "Failed to parse classification."})
            triaged.append({**thread, **label})

    except Exception:
        # Fallback to local rule-based triage if API call fails
        triaged = []
        for thread in threads:
            sub = thread.get("subject", "").lower()
            snippet_lower = thread.get("snippet", "").lower()
            sender_lower = thread.get("sender", "").lower()

            priority = "fyi"
            category = "other"
            reason = "Rule-based fallback triage (LLM rate-limited/failed)."

            # Simple keyword matching rules
            if any(k in sub or k in snippet_lower for k in ["urgent", "outage", "critical", "asap", "emergency", "blocker"]):
                priority = "urgent"
                category = "alert"
                reason = "Identified keywords associated with urgent tasks (fallback)."
            elif any(k in sub or k in snippet_lower for k in ["feedback", "discuss", "review", "contract", "meeting", "call", "schedule", "questions"]):
                priority = "needs-reply"
                category = "follow-up"
                reason = "Flagged for follow-up review/response (fallback)."
            elif any(k in sub or k in snippet_lower for k in ["standup", "weekly", "notes", "newsletter", "update"]):
                priority = "fyi"
                category = "admin"
                reason = "Classified as informational update (fallback)."
            elif any(k in sub or k in snippet_lower or k in sender_lower for k in ["marketing", "promo", "newsletter", "sale", "subscribe"]):
                priority = "ignore"
                category = "newsletter"
                reason = "Identified as newsletter/marketing (fallback)."

            triaged.append({**thread, "priority": priority, "category": category, "reason": reason})

    # Sort by priority
    priority_order = {"urgent": 0, "needs-reply": 1, "fyi": 2, "ignore": 3, "unknown": 4}
    triaged.sort(key=lambda x: priority_order.get(x["priority"], 4))

    return triaged


def format_digest(results: list) -> None:
    """
    Print a clean, readable digest of triaged threads to the terminal.

    Assumes `results` is the sorted output of `triage_inbox()` (sorted by
    priority, urgent first). Groups threads by priority with a separator
    line between groups, and prints a header with today's date and the
    total number of threads.
    """
    from datetime import datetime

    # Priority groups in the order we want them displayed. The incoming
    # list is already sorted by `triage_inbox`, but we re-group here so
    # the separator logic stays correct even if the caller passes an
    # unsorted list.
    group_order = ["urgent", "needs-reply", "fyi", "ignore", "unknown"]
    priority_label = {
        "urgent": "URGENT",
        "needs-reply": "NEEDS-REPLY",
        "fyi": "FYI",
        "ignore": "IGNORE",
        "unknown": "UNKNOWN",
    }

    today = datetime.now().strftime("%Y-%m-%d")
    total = len(results)

    # Header
    print("=" * 60)
    print(f"INBOX DIGEST  |  {today}  |  {total} thread(s)")
    print("=" * 60)

    if total == 0:
        print("(no threads to display)")
        return

    # Walk groups in display order and emit a separator between them.
    first_group_emitted = False
    for group in group_order:
        group_items = [r for r in results if r.get("priority") == group]
        if not group_items:
            continue

        if first_group_emitted:
            print("-" * 60)

        first_group_emitted = True

        for r in group_items:
            label = priority_label.get(group, group.upper())
            sender = r.get("sender", "")
            subject = r.get("subject", "")
            reason = r.get("reason", "")
            print(f"[{label}] {sender} | {subject} — {reason}")

# Replace this with your actual Gmail thread fetch from Day 2
'''sample_threads = [
    {"sender": "boss@company.com", "subject": "Need your input by EOD", "snippet": "Can you review the attached proposal before 5pm?"},
    {"sender": "newsletter@medium.com", "subject": "Top stories for you this week", "snippet": "Here's what's trending in tech..."},
    {"sender": "recruiter@startup.io", "subject": "Quick call this week?", "snippet": "Hi, I came across your profile and wanted to connect..."},
]

results = triage_inbox(sample_threads)

format_digest(results)'''




