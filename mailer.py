"""Mailer Agent — map reviewed drafts to recipients and send via Gmail."""

import re
import base64
from pathlib import Path
from email.mime.text import MIMEText


def log(tag: str, msg: str = ""):
    """Formatted log: [TAG] message"""
    print(f"[{tag}] {msg}", flush=True)

# ── Project root ─────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent


# ══════════════════════════════════════════════════════════════════════
# PART 1 — DRAFT REGISTRY
# ══════════════════════════════════════════════════════════════════════
# Each entry: {"file_path": str, "title": str, "subject": str}
# Populated externally (e.g. by the Drafter Agent after finalization).
# DO NOT scan directories — only use this registry.
DRAFTS: list[dict] = []


def register_draft(file_path: str, title: str, subject: str):
    """Add a draft to the global DRAFTS registry."""
    DRAFTS.append({
        "file_path": file_path,
        "title": title,
        "subject": subject,
    })
    log("MAILER", f"Registered draft: {title}")


# ══════════════════════════════════════════════════════════════════════
# PART 2 — MAPPING FUNCTION
# ══════════════════════════════════════════════════════════════════════
def map_drafts_to_recipients(user_input: str, drafts: list) -> list[dict]:
    """
    Parse natural-language input and match drafts by keyword.

    Input examples:
        "send outreach mail to Rahul, pitch mail to Aman"
        "send absence mail to Professor"

    Returns:
        [{"file_path": "...", "recipient": "..."}]
    """
    if not drafts:
        log("MAILER:ERROR", "DRAFTS registry is empty — nothing to map.")
        return []

    # Split on comma to get individual instructions
    parts = [p.strip() for p in user_input.split(",") if p.strip()]
    mappings: list[dict] = []

    for part in parts:
        # Extract recipient — last token after "to" (name or email)
        to_match = re.search(r"\bto\s+([\w@.\-+]+)\s*$", part, re.IGNORECASE)
        if not to_match:
            log("MAILER:ERROR", f"No recipient found in: '{part}'")
            continue
        recipient = to_match.group(1).strip()

        # Keywords = everything before "to <recipient>", stripped of filler
        keyword_section = part[:to_match.start()].lower()
        # Remove common filler words
        filler = {"send", "the", "a", "an", "my", "please", "mail", "email"}
        keywords = [w for w in keyword_section.split() if w not in filler]

        if not keywords:
            log("MAILER:ERROR", f"No keywords to match draft in: '{part}'")
            continue

        # Match against draft titles — best match wins
        best_draft = None
        best_score = 0
        for draft in drafts:
            title_lower = draft["title"].lower()
            score = sum(1 for kw in keywords if kw in title_lower)
            if score > best_score:
                best_score = score
                best_draft = draft

        if best_draft is None or best_score == 0:
            log("MAILER:ERROR", f"No draft matched keywords {keywords}")
            continue

        mappings.append({
            "file_path": best_draft["file_path"],
            "recipient": recipient,
        })
        log("MAILER", f"Mapped '{best_draft['title']}' → {recipient}")

    return mappings


# ══════════════════════════════════════════════════════════════════════
# PART 3 — SEND QUEUE
# ══════════════════════════════════════════════════════════════════════
SEND_QUEUE: list[dict] = []


def build_send_queue(mappings: list[dict]) -> list[dict]:
    """Stamp provider and populate the global SEND_QUEUE."""
    global SEND_QUEUE
    SEND_QUEUE = []
    for m in mappings:
        SEND_QUEUE.append({
            "file_path": m["file_path"],
            "recipient": m["recipient"],
            "provider": "gmail",
        })
    log("MAILER", f"SEND_QUEUE built — {len(SEND_QUEUE)} item(s)")
    return SEND_QUEUE


# ══════════════════════════════════════════════════════════════════════
# PART 4 — EMAIL CONTENT EXTRACTION
# ══════════════════════════════════════════════════════════════════════
def _read_and_clean(file_path: str) -> dict:
    """
    Read a draft file and extract subject + body.

    Strips markers:  — EMAIL DRAFT —  /  — END —
    Extracts:        Subject: ...     /  Body: ...

    Returns: {"subject": str, "body": str}
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Draft file not found: {file_path}")

    raw = path.read_text(encoding="utf-8")

    # Strip markers (em-dash style used by drafter.py)
    raw = re.sub(r"—\s*EMAIL DRAFT\s*—", "", raw)
    raw = re.sub(r"—\s*END\s*—", "", raw)
    # Also handle triple-dash variants just in case
    raw = re.sub(r"---\s*EMAIL DRAFT\s*---", "", raw)
    raw = re.sub(r"---\s*END\s*---", "", raw)
    raw = raw.strip()

    # Extract subject
    subject = ""
    subject_match = re.search(r"^Subject:\s*(.+)$", raw, re.MULTILINE)
    if subject_match:
        subject = subject_match.group(1).strip()

    # Extract body — everything after "Body:" line
    body = ""
    body_match = re.search(r"^Body:\s*\n(.*)", raw, re.MULTILINE | re.DOTALL)
    if body_match:
        body = body_match.group(1).strip()
    else:
        # Fallback: use everything after subject line
        body = raw

    return {"subject": subject, "body": body}


# ══════════════════════════════════════════════════════════════════════
# PART 5 — GMAIL IMPLEMENTATION
# ══════════════════════════════════════════════════════════════════════
_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
_CREDS_FILE = _PROJECT_ROOT / "credentials.json"
_TOKEN_FILE = _PROJECT_ROOT / "token.json"


def _get_gmail_service():
    """Authenticate and return the Gmail API service object."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None

    # 1 — Load saved token
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)

    # 2 — Refresh or re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log("GMAIL", "Refreshing expired token…")
            creds.refresh(Request())
        else:
            if not _CREDS_FILE.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {_CREDS_FILE}\n"
                    "Download it from Google Cloud Console → APIs → Credentials"
                )
            log("GMAIL", "Opening browser for OAuth consent…")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_CREDS_FILE), _SCOPES
            )
            creds = flow.run_local_server(port=0)

        # 3 — Save token for next time
        _TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        log("GMAIL", "Token saved.")

    # 4 — Build service
    service = build("gmail", "v1", credentials=creds)
    log("GMAIL", "Service ready.")
    return service


def _send_via_gmail(to: str, subject: str, body: str) -> dict:
    """Compose and send a single email via Gmail API."""
    service = _get_gmail_service()

    # Build MIME message
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    # Encode to base64url
    raw_bytes = message.as_bytes()
    encoded = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    # Send
    result = service.users().messages().send(
        userId="me",
        body={"raw": encoded},
    ).execute()

    log("GMAIL", f"Sent → {to} (Message ID: {result.get('id', '?')})")
    return result


# ══════════════════════════════════════════════════════════════════════
# PART 4+5 COMBINED — SEND EMAIL
# ══════════════════════════════════════════════════════════════════════
def send_email(task: dict) -> dict:
    """
    Read draft, clean content, send via Gmail.

    Args:
        task: {"file_path": str, "recipient": str, "provider": str}

    Returns:
        {"status": "sent", "recipient": str, "file_path": str}
    """
    # ── Safety checks (PART 6) ───────────────────────────────────────
    file_path = task.get("file_path")
    recipient = task.get("recipient")

    if not file_path:
        raise ValueError("Task is missing 'file_path'")
    if not recipient:
        raise ValueError("Task is missing 'recipient'")

    # Verify the draft exists in the registry
    registered_paths = {d["file_path"] for d in DRAFTS}
    if file_path not in registered_paths:
        raise ValueError(
            f"Draft '{file_path}' is NOT in the DRAFTS registry. "
            "Only registered drafts can be sent."
        )

    # ── Read and clean ───────────────────────────────────────────────
    content = _read_and_clean(file_path)
    log("MAILER", f"Subject: {content['subject']}")
    log("MAILER", f"Body length: {len(content['body'])} chars")

    # ── Send ─────────────────────────────────────────────────────────
    _send_via_gmail(
        to=recipient,
        subject=content["subject"],
        body=content["body"],
    )

    return {
        "status": "sent",
        "recipient": recipient,
        "file_path": file_path,
    }


# ══════════════════════════════════════════════════════════════════════
# PART 8 — TEST BLOCK
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  📬  Mailer Agent — Test Run")
    print("=" * 55)

    # ── Step 1: Populate DRAFTS registry ─────────────────────────────
    print("\n--- Step 1: Registering drafts ---")
    _test_mail = _PROJECT_ROOT / "Drafts" / "Mail" / "Absence_IDE_Bootcamp_6to10.txt"
    register_draft(
        file_path=str(_test_mail),
        title="Absence IDE Bootcamp",
        subject="Absence Due to IDE Bootcamp from 6th to 10th",
    )
    print(f"  DRAFTS: {DRAFTS}")

    # ── Step 2: Map drafts → recipients ──────────────────────────────
    print("\n--- Step 2: Mapping drafts to recipients ---")
    user_command = "send absence bootcamp mail to professor@example.com"
    mappings = map_drafts_to_recipients(user_command, DRAFTS)
    print(f"  Mappings: {mappings}")

    # ── Step 3: Build SEND_QUEUE ─────────────────────────────────────
    print("\n--- Step 3: Building SEND_QUEUE ---")
    queue = build_send_queue(mappings)
    print(f"  SEND_QUEUE: {queue}")

    # ── Step 4: Send emails ──────────────────────────────────────────
    print("\n--- Step 4: Sending emails ---")
    for task in SEND_QUEUE:
        try:
            result = send_email(task)
            print(f"  ✅ {result}")
        except FileNotFoundError as e:
            print(f"  ❌ File error: {e}")
        except ValueError as e:
            print(f"  ❌ Safety error: {e}")
        except Exception as e:
            print(f"  ❌ Gmail error: {e}")
            print("     (Make sure credentials.json is present and Gmail API is enabled)")

    print("\n" + "=" * 55)
    print("  Test complete.")
    print("=" * 55)
