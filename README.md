# Chief of Staff — Draft Desk

An AI-powered email workflow assistant that helps turn a crowded inbox into clear priorities and reviewable email drafts — with a human approval gate before actions proceed.

## Overview

Chief of Staff — Draft Desk is designed to reduce repetitive email work by organizing incoming threads, identifying what needs attention, and generating drafts for human review.

Instead of letting AI take actions without oversight, Draft Desk keeps the user in control through an explicit approval workflow.

## Features

- **Inbox & Triage:** Retrieve threads from the selected source and organize them by priority.
- **AI-assisted drafting:** Generate email drafts based on the selected threads and available context.
- **Human approval gate:** Review, edit, approve, regenerate, or reject drafts before they proceed.
- **Action log:** View recorded workflow actions and their statuses.
- **Session proof:** Review session-level evidence of approved drafts and workflow activity.
- **Multiple source modes:** Use sample threads in the hosted demo; Gmail mode requires email integration and configuration in code.

## Workflow

1. Select an email source.
2. Run the pipeline to fetch and triage threads.
3. Generate drafts for relevant messages.
4. Review each draft at the Approval Gate.
5. Approve, edit, regenerate, or reject the draft.
6. Review the recorded activity in the Action Log and Session Proof.

> Human approval is a core design principle: generated drafts should be reviewed before any consequential action.

## Application Screenshots

### Inbox & Triage
![Inbox and Triage](screenshots/inbox_and_triage.png)

### Approval Gate
![Approval Gate](screenshots/approval_gate.png)

### Action Log
![Action Log](screenshots/action_log.png)

### Session Proof
![Session Proof](screenshots/session_proof.png)

## Tech Stack

- Python
- Streamlit
- Google Gemini API
- Email/Gmail integration
- Git and GitHub

## Run Locally

1. Clone the repository:

   ```bash
   git clone https://github.com/noshinip27-cyber/Chief_of_staff.git
   cd Chief_of_staff
   ```

2. Create and activate a virtual environment (recommended):

   **Windows**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

   **macOS/Linux**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies, if a `requirements.txt` file is present:

   ```bash
   pip install -r requirements.txt
   ```

4. Configure the required API key and other settings using your project's expected environment variables or secrets. Never commit API keys, passwords, tokens, or private email credentials.

5. Start the Streamlit application using the entry-point file configured in your repository. For example, if it is `app.py`:

   ```bash
   streamlit run app.py
   ```

## Security & Responsible AI

- Keep API keys and credentials out of source control.
- Review AI-generated drafts before approving them.
- Configure Gmail access securely before using a real email account.
- Do not assume that a draft has been sent or a meeting booked unless the configured integration confirms the action.

## Current Demo Notes

The hosted demo uses sample threads. Gmail-based processing requires the corresponding email integration and configuration in code. Availability of actions depends on the configured integrations.

## Future Improvements

- More robust email-provider integration and error handling.
- Better context handling for replies and meeting-related requests.
- Expanded audit history and workflow testing.
- Clearer status reporting for completed and failed actions.

## Author

Built as an AI workflow automation project exploring email triage, draft generation, and human-in-the-loop approval.

---

If you find this project interesting, feel free to explore the code and share feedback.
