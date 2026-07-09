"""
approval_gate.py — Human in the Loop
A Streamlit app that shows email thread + AI draft, then lets the user
Approve, Edit, or Reject the draft before it's "sent."

Run with: streamlit run approval_gate.py
"""

import os
import json
import streamlit as st
from datetime import datetime
from context_builder import assemble_context, format_thread_history
from draft_machine import draft_reply, SAMPLE_THREADS


# ============================================================
# CONFIG & SETUP
# ============================================================

st.set_page_config(
    page_title="Draft Desk — Approval Gate",
    page_icon="✉️",
    layout="wide"
)

st.markdown("""
<style>
    .stApp {
        background-color: #0e1117;
    }
    .placeholder-box {
        background-color: #16213e;
        border: 1px solid #2b3a55;
        border-radius: 10px;
        padding: 18px;
        margin: 10px 0;
        color: #a8b3cf;
    }
    .draft-box {
        background-color: #16213e;
        border: 1px solid #00b4d8;
        border-radius: 10px;
        padding: 20px;
        margin: 10px 0;
        color: #ffffff;
        font-family: 'Segoe UI', sans-serif;
    }
    .thread-box {
        background-color: #0f3460;
        border: 1px solid #2ecc71;
        border-radius: 10px;
        padding: 15px;
        margin: 8px 0;
        color: #cccccc;
    }
    .status-approved {
        background-color: #1a4a2e;
        border: 2px solid #2ecc71;
        border-radius: 10px;
        padding: 15px;
        color: #2ecc71;
        font-weight: bold;
    }
    .status-rejected {
        background-color: #4a1a1a;
        border: 2px solid #e74c3c;
        border-radius: 10px;
        padding: 15px;
        color: #e74c3c;
        font-weight: bold;
    }
    .api-key-ok {
        background-color: #1a4a2e;
        border: 1px solid #2ecc71;
        border-radius: 8px;
        padding: 10px 14px;
        color: #2ecc71;
        font-size: 0.9rem;
        margin-top: 6px;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def save_approved_draft(draft_data):
    """Save an approved draft to approved_drafts.json."""
    filepath = "approved_drafts.json"
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            approved = json.load(f)
    else:
        approved = []
    draft_data["approved_at"] = datetime.now().isoformat()
    approved.append(draft_data)
    with open(filepath, "w") as f:
        json.dump(approved, f, indent=2)
    return len(approved)


def render_thread(thread):
    """Render the email thread in a readable format."""
    st.markdown(f"**Subject: {thread['subject']}**")
    st.markdown("---")
    for msg in thread["messages"]:
        sender = msg["from"]
        date = msg["date"]
        body = msg["body"]
        is_you = "you@" in sender.lower()
        icon = "🟢" if is_you else "🔵"
        st.markdown(
            f'<div class="thread-box">'
            f'<strong>{icon} {sender}</strong> &nbsp; <em>{date}</em><br><br>'
            f'{body}'
            f'</div>',
            unsafe_allow_html=True
        )


# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================

if "draft" not in st.session_state:
    st.session_state.draft = None
if "status" not in st.session_state:
    st.session_state.status = None  # None, "approved", "editing", "rejected"
if "selected_thread" not in st.session_state:
    st.session_state.selected_thread = None
if "edit_text" not in st.session_state:
    st.session_state.edit_text = ""
if "generation_count" not in st.session_state:
    st.session_state.generation_count = 0


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.markdown("### 🛡️ Approval Gate")
st.sidebar.markdown("---")

st.sidebar.markdown("#### 📧 Email thread")

PLACEHOLDER = "-- Select a sample thread --"
thread_options = [PLACEHOLDER] + [t["subject"] for t in SAMPLE_THREADS]

st.sidebar.markdown("Sample thread")
selected_subject = st.sidebar.selectbox(
    "Choose a sample thread:",
    options=thread_options,
    index=0,
    label_visibility="collapsed"
)

selected_thread = None
if selected_subject != PLACEHOLDER:
    selected_thread = next(t for t in SAMPLE_THREADS if t["subject"] == selected_subject)

st.sidebar.markdown("")
use_custom = st.sidebar.checkbox("Use custom thread")

if use_custom:
    st.sidebar.markdown("Or paste a custom thread")
    st.sidebar.markdown("Paste thread JSON:")
    custom_thread_json = st.sidebar.text_area(
        "Paste thread JSON:",
        height=120,
        placeholder='{"subject": "...", "messages": [{"from": "...", "date": "...", "body": "..."}]}',
        label_visibility="collapsed"
    )
    if custom_thread_json:
        try:
            selected_thread = json.loads(custom_thread_json)
            st.sidebar.success("Custom thread loaded!")
        except json.JSONDecodeError:
            st.sidebar.error("Invalid JSON. Check the format.")
            selected_thread = None

st.sidebar.markdown("---")
generate_clicked = st.sidebar.button("🚀 Generate Draft", use_container_width=True)

if generate_clicked:
    if not selected_thread:
        st.sidebar.error("Please select or paste a thread first.")
    else:
        st.session_state.selected_thread = selected_thread
        st.session_state.status = None
        st.session_state.edit_text = ""
        with st.spinner("Generating draft with Gemini..."):
            try:
                draft = draft_reply(selected_thread)
                st.session_state.draft = draft
                st.session_state.generation_count += 1
            except Exception as e:
                st.error(f"Error generating draft: {e}")
                st.session_state.draft = None

st.sidebar.markdown("---")
st.sidebar.markdown("#### 🔑 API key")
if os.environ.get("GEMINI_API_KEY"):
    st.sidebar.markdown(
        '<div class="api-key-ok">✅ GEMINI_API_KEY found in environment</div>',
        unsafe_allow_html=True
    )
else:
    st.sidebar.warning("⚠️ GEMINI_API_KEY not found. Add it to your .env file.")

st.sidebar.markdown("---")

if os.path.exists("approved_drafts.json"):
    with open("approved_drafts.json", "r") as f:
        approved = json.load(f)
    st.sidebar.metric("Approved Drafts", len(approved))


# ============================================================
# MAIN CONTENT
# ============================================================

st.markdown("## 🛡️ Human-in-the-Loop Approval Gate")
st.caption("Review the AI-generated draft below, then **APPROVE**, **EDIT**, or **REJECT** it. Nothing is sent without your explicit approval.")

col_thread, col_draft = st.columns([1, 1])

with col_thread:
    st.markdown("#### 📨 Email thread")
    if st.session_state.selected_thread and st.session_state.draft:
        render_thread(st.session_state.selected_thread)
    else:
        st.markdown(
            '<div class="placeholder-box">👉 Pick a thread in the sidebar (sample or paste your own JSON) '
            'and click <strong>Generate Draft</strong>.</div>',
            unsafe_allow_html=True
        )

with col_draft:
    st.markdown("#### ✍️ AI draft reply")

    if not (st.session_state.selected_thread and st.session_state.draft):
        st.markdown(
            '<div class="placeholder-box">No draft yet. Pick a thread and click '
            '<strong>Generate Draft</strong> in the sidebar.</div>',
            unsafe_allow_html=True
        )
    else:
        st.caption(f"Generation #{st.session_state.generation_count}")

        if st.session_state.status == "editing":
            st.session_state.edit_text = st.text_area(
                "Edit the draft:",
                value=st.session_state.edit_text or st.session_state.draft,
                height=300,
                key="edit_area"
            )
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("✅ Approve Edited Draft", use_container_width=True):
                    st.session_state.draft = st.session_state.edit_text
                    st.session_state.status = "approved"
                    count = save_approved_draft({
                        "thread_subject": st.session_state.selected_thread["subject"],
                        "draft": st.session_state.draft,
                        "was_edited": True
                    })
                    st.success(f"Draft approved and saved! ({count} total approved)")
                    st.rerun()
            with col_cancel:
                if st.button("↩️ Cancel Edit", use_container_width=True):
                    st.session_state.status = None
                    st.rerun()

        elif st.session_state.status == "approved":
            st.markdown(
                '<div class="status-approved">APPROVED — Ready to send</div>',
                unsafe_allow_html=True
            )
            st.markdown("---")
            st.markdown(f'<div class="draft-box">{st.session_state.draft}</div>', unsafe_allow_html=True)
            st.balloons()

        elif st.session_state.status == "rejected":
            st.markdown(
                '<div class="status-rejected">REJECTED — Draft discarded</div>',
                unsafe_allow_html=True
            )
            st.info("Click 'Generate Draft' in the sidebar to try again, or select a different thread.")

        else:
            st.markdown(f'<div class="draft-box">{st.session_state.draft}</div>', unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("**What do you want to do with this draft?**")
            col_approve, col_edit, col_reject = st.columns(3)
            with col_approve:
                if st.button("✅ Approve", use_container_width=True, type="primary"):
                    st.session_state.status = "approved"
                    count = save_approved_draft({
                        "thread_subject": st.session_state.selected_thread["subject"],
                        "draft": st.session_state.draft,
                        "was_edited": False
                    })
                    st.success(f"Saved! ({count} total)")
                    st.rerun()
            with col_edit:
                if st.button("✏️ Edit", use_container_width=True):
                    st.session_state.status = "editing"
                    st.session_state.edit_text = st.session_state.draft
                    st.rerun()
            with col_reject:
                if st.button("❌ Reject", use_container_width=True):
                    st.session_state.status = "rejected"
                    st.rerun()

st.markdown("---")
with st.expander("ℹ️ How this gate works"):
    st.markdown("""
    1. Pick an email thread from the sidebar (or paste your own)
    2. Click **Generate Draft** — the AI writes a reply in your voice
    3. Review the draft and choose:
       - **Approve** — marks it ready to send, saves to `approved_drafts.json`
       - **Edit** — opens a text editor so you can tweak it, then approve
       - **Reject** — discards the draft; regenerate or skip

    **The key principle:** Never auto-send without human approval.
    """)