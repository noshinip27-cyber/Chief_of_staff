"""
Draft Machine — MS2.2: The Draft Machine
Calls Gemini (gemini-1.5-flash) with assembled context to generate
email replies that match your tone and follow the one-ask rule.
"""

import os
import time
import google.generativeai as genai
from dotenv import load_dotenv
from context_builder import assemble_context

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash-lite")

def _generate_with_retry(prompt: str, max_retries: int = 5, base_delay: float = 20.0) -> str:
    """
    Call model.generate_content with automatic retry on quota / rate-limit errors.
    Waits `base_delay` seconds on the first retry, doubling each time.
    """
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            err_str = str(e)
            # 429 = quota exceeded / rate limited
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                if attempt < max_retries - 1:
                    wait = base_delay * (2 ** attempt)
                    print(f"[draft_machine] Rate limit hit — waiting {wait:.0f}s before retry {attempt + 2}/{max_retries}…")
                    time.sleep(wait)
                    continue
            raise  # re-raise non-quota errors or final attempt
    raise RuntimeError("Failed to generate draft after retries.")


DRAFTING_RULES = """

CRITICAL DRAFTING RULES:
1. ONE-ASK RULE: Every email must have exactly ONE clear question or ONE clear response.
   Never bury multiple asks. If you need to address multiple points, make ONE the focus
   and handle the rest as statements.

2. LENGTH CONTROL:
   - Match the energy of the thread (short thread = short reply)
   - Quick replies: 2-3 sentences max
   - Substantive replies: 5 sentences max, use numbered points if needed
   - NEVER write more than the sender wrote unless adding essential info

3. NO AI FILLER:
   - Never say "I hope this email finds you well"
   - Never say "Thank you for reaching out"
   - Never say "I wanted to follow up on"
   - Never say "Please don't hesitate to"
   - Never start with "I" — start with the content

4. STRUCTURE:
   - Acknowledge their point briefly (1 line max)
   - Give your response/decision
   - End with ONE clear next step or question
"""


# ============================================================
# Sample data (importable by other modules, e.g. approval_gate.py)
# ============================================================
SAMPLE_THREADS = [
    {
        "subject": "Q3 Budget Review",
        "messages": [
            {
                "from": "boss@company.com",
                "date": "June 10, 2:30 PM",
                "body": "Can you review the Q3 budget doc and share your thoughts by EOD tomorrow? Specifically the marketing allocation — I think we're overspending on paid ads."
            },
            {
                "from": "you@company.com",
                "date": "June 10, 3:15 PM",
                "body": "Got it, will review tonight. Quick question — should I loop in the marketing team lead or keep it between us?"
            },
            {
                "from": "boss@company.com",
                "date": "June 11, 9:00 AM",
                "body": "Keep it between us for now. Let me know what you find."
            }
        ]
    }
]


def draft_reply(thread, tone_path="tone_profile.json", replies_path="past_replies.json"):
    """
    Generate a draft email reply for the given thread.

    Uses:
    - Context builder (tone profile + past replies + thread history)
    - Gemini 2.5 Flash model
    - One-ask rule: every reply has exactly ONE clear question or response
    - Length control: keep replies concise and match thread energy

    Args:
        thread: dict with 'subject' and 'messages' list
        tone_path: path to tone_profile.json
        replies_path: path to past_replies.json

    Returns:
        str: the drafted reply text
    """
    context = assemble_context(thread, tone_path, replies_path)

    full_prompt = f"""{context['system']}
{DRAFTING_RULES}

---

{context['user']}

IMPORTANT: Output ONLY the email reply text. No subject line, no explanation, no markdown. Just the reply body as you would type it in Gmail."""

    return _generate_with_retry(full_prompt)


def draft_reply_with_metadata(thread, tone_path="tone_profile.json", replies_path="past_replies.json"):
    """
    Like draft_reply() but returns metadata about the generation too.
    Useful for debugging and the approval workflow (MS2.3).
    """
    context = assemble_context(thread, tone_path, replies_path)

    full_prompt = f"""{context['system']}
{DRAFTING_RULES}

---

{context['user']}

IMPORTANT: Output ONLY the email reply text. No subject line, no explanation, no markdown. Just the reply body as you would type it in Gmail."""

    draft = _generate_with_retry(full_prompt)

    return {
        "draft": draft,
        "model": "gemini-2.5-flash-lite",
        "thread_subject": thread["subject"],
        "reply_to": thread["messages"][-1]["from"],
    }


# ============================================================
# Demo: Run on a sample thread
# ============================================================
if __name__ == "__main__":
    sample_thread = SAMPLE_THREADS[0]

    print("=" * 60)
    print("DRAFT MACHINE — MS2.2")
    print("=" * 60)
    print(f"\nThread: {sample_thread['subject']}")
    print(f"Replying to: {sample_thread['messages'][-1]['from']}")
    print(f"Their message: {sample_thread['messages'][-1]['body']}")
    print("\n" + "-" * 60)
    print("GENERATING DRAFT...")
    print("-" * 60 + "\n")

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not set!")
        print("Set it in your .env file or environment.")
        exit(1)

    result = draft_reply_with_metadata(sample_thread)

    print("DRAFT REPLY:")
    print("=" * 60)
    print(result["draft"])
    print("=" * 60)
    print(f"\nModel: {result['model']}")
    print(f"Replying to: {result['reply_to']}")
    print(f"Subject: {result['thread_subject']}")