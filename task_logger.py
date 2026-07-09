import json
import os
from datetime import datetime, timezone

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "action_log.json")


def log_action(action_type: str, thread_subject: str, detail: str, action_id: str) -> None:
    """
    Appends a record to action_log.json.

    Args:
        action_type:     "sent" or "booked"
        thread_subject:  Subject line of the email thread
        detail:          Recipient email (for "sent") or meeting title (for "booked")
        action_id:       Gmail message_id or Google Calendar event_id
    """
    if action_type not in ("sent", "booked"):
        raise ValueError(f"action_type must be 'sent' or 'booked', got {action_type!r}")

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action_type": action_type,
        "thread_subject": thread_subject,
        "detail": detail,
        "id": action_id,
    }

    log = get_action_log()
    log.append(record)

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def get_action_log() -> list:
    """
    Reads action_log.json and returns the full list of records.
    Returns [] if the file does not exist or is empty.
    """
    if not os.path.exists(LOG_FILE):
        return []

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return []

    return json.loads(content)


def clear_log() -> None:
    """Writes an empty list to action_log.json."""
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)


if __name__ == "__main__":
    print("Clearing existing log...")
    clear_log()

    print("Logging a 'sent' action...")
    log_action(
        action_type="sent",
        thread_subject="Re: Project Update",
        detail="alice@example.com",
        action_id="msg_abc123",
    )

    print("Logging a 'booked' action...")
    log_action(
        action_type="booked",
        thread_subject="Sync with Bob",
        detail="Weekly Sync",
        action_id="event_xyz456",
    )

    print("\nCurrent action log:")
    import json
    print(json.dumps(get_action_log(), indent=2))
