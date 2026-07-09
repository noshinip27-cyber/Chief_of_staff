import json


def load_tone_profile(path="tone_profile.json"):
    """Load the user's tone/persona profile."""
    with open(path, "r") as f:
        return json.load(f)


def load_past_replies(path="past_replies.json"):
    """Load past reply examples for few-shot prompting."""
    with open(path, "r") as f:
        return json.load(f)


def format_thread_history(thread):
    """Format a thread into a readable chronological string."""
    output = f"Subject: {thread['subject']}\n"
    output += "=" * 50 + "\n\n"

    for msg in thread["messages"]:
        output += f"From: {msg['from']}\n"
        output += f"Date: {msg['date']}\n"
        output += f"{msg['body']}\n"
        output += "-" * 40 + "\n\n"

    return output.strip()


def build_system_prompt(tone_profile, past_replies):
    """Build the system prompt with persona + few-shot examples."""
    name = tone_profile["name"]
    role = tone_profile["role"]

    # Persona description
    prompt = f"""You are drafting email replies for {name}, a {role}.

Tone: {tone_profile['tone']}
Formality: {tone_profile['formality']}
Sentence length: {tone_profile['sentence_length']}
Greeting: {tone_profile['greeting_style']}
Sign-off: {tone_profile['sign_off']}

Writing rules:
"""
    for quirk in tone_profile["quirks"]:
        prompt += f"- {quirk}\n"

    # Few-shot examples
    prompt += f"\nHere are examples of how {name} actually writes emails:\n\n"

    for i, reply in enumerate(past_replies, 1):
        prompt += f"--- Example {i} (Re: {reply['subject']}) ---\n"
        prompt += f"{reply['body']}\n\n"

    prompt += f"""---

Match this writing style exactly. Sound like {name}, not like an AI assistant.
Never use generic filler phrases. Be direct and human."""

    return prompt


def build_user_prompt(thread_formatted):
    """Build the user message with the thread to reply to."""
    return f"""Here's the email thread I need to reply to:

{thread_formatted}

Draft a reply to the latest message in this thread.
- Match my tone and style from the examples above
- Keep it concise — one clear response or ask
- Don't repeat what they already said
- End with a clear next step if appropriate"""


def assemble_context(thread, tone_path="tone_profile.json", replies_path="past_replies.json"):
    """Main function: assemble the full prompt context."""
    tone_profile = load_tone_profile(tone_path)
    past_replies = load_past_replies(replies_path)

    thread_formatted = format_thread_history(thread)
    system_prompt = build_system_prompt(tone_profile, past_replies)
    user_prompt = build_user_prompt(thread_formatted)

    return {
        "system": system_prompt,
        "user": user_prompt
    }


# Demo: run on a sample thread
if __name__ == "__main__":
    sample_thread = {
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

    context = assemble_context(sample_thread)

    print("=" * 60)
    print("SYSTEM PROMPT:")
    print("=" * 60)
    print(context["system"])
    print("\n" + "=" * 60)
    print("USER PROMPT:")
    print("=" * 60)
    print(context["user"])
