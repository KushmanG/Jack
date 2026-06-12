"""Drafter Agent — create and finalize email/report drafts."""

import subprocess
from pathlib import Path
from llm import generate_with_llm
from utils import log

# ── Global state ─────────────────────────────────────────────────────
CURRENT_TASK: dict | None = None

# Project root for Drafts folder
_PROJECT_ROOT = Path(__file__).parent


# ── Draft creation ───────────────────────────────────────────────────
def create_draft(user_input: str, draft_type: str):
    """Generate a draft (email or report), save to file, open in VS Code."""
    global CURRENT_TASK

    if draft_type not in ("email", "report"):
        log("DRAFTER:ERROR", f"Unknown draft type: {draft_type}")
        return

    # 1 — Generate structured content via LLM
    if draft_type == "email":
        prompt = (
            f"Write a professional email based on: {user_input}\n\n"
            f"Respond strictly in this format:\n"
            f"Subject: <subject line>\n\n"
            f"Body:\n<email body>"
        )
    else:
        prompt = (
            f"Write a professional report based on: {user_input}\n\n"
            f"Respond strictly in this format:\n"
            f"Title: <title>\n\n"
            f"Content:\n<report content>"
        )

    log("DRAFTER", f"Generating {draft_type} draft…")
    raw = generate_with_llm(prompt)

    # 2 — Extract metadata
    if draft_type == "email":
        subject = ""
        for line in raw.splitlines():
            if line.lower().startswith("subject:"):
                subject = line.split(":", 1)[1].strip()
                break
        metadata = {"subject": subject}
    else:
        title = ""
        for line in raw.splitlines():
            if line.lower().startswith("title:"):
                title = line.split(":", 1)[1].strip()
                break
        metadata = {"title": title}

    meta_value = metadata.get("subject") or metadata.get("title") or "draft"
    log("DRAFTER", f"Extracted metadata: {meta_value}")

    # 3 — Generate filename via LLM
    filename_prompt = (
        f"Give a short 2-4 word filename (no extension, no spaces, use underscores) "
        f"for this content:\n{meta_value}\n\n"
        f"Respond with ONLY the filename, nothing else."
    )
    filename_raw = generate_with_llm(filename_prompt)
    # Clean up: strip quotes, spaces, extension if LLM added one
    filename = filename_raw.strip().strip("\"'").replace(" ", "_")
    if filename.endswith(".txt"):
        filename = filename[:-4]
    filename = filename + ".txt"
    log("DRAFTER", f"Filename: {filename}")

    # 4 — Create folder
    if draft_type == "email":
        folder = _PROJECT_ROOT / "Drafts" / "Mail"
    else:
        folder = _PROJECT_ROOT / "Drafts" / "Reports"
    folder.mkdir(parents=True, exist_ok=True)

    # 5 — Format file content
    if draft_type == "email":
        content = f"— EMAIL DRAFT —\n\n{raw}\n\n— END —"
    else:
        content = f"— REPORT —\n\n{raw}\n\n— END —"

    # 6 — Write file
    file_path = folder / filename
    file_path.write_text(content, encoding="utf-8")
    log("DRAFTER", f"Saved: {file_path}")

    # 7 — Open in VS Code
    try:
        subprocess.run(["code", str(file_path)], check=False)
        log("DRAFTER", "Opened in VS Code.")
    except FileNotFoundError:
        log("DRAFTER:WARN", "'code' not found — skipping VS Code.")

    # 8 — Update global state
    CURRENT_TASK = {
        "type": draft_type,
        "status": "waiting_review",
        "file_path": str(file_path),
        "metadata": metadata,
    }
    log("DRAFTER", f"Draft ready for review. Status: waiting_review")


# ── Draft finalization ───────────────────────────────────────────────
def finalize_draft() -> dict | None:
    """Read the reviewed draft file and return structured output."""
    global CURRENT_TASK

    if CURRENT_TASK is None:
        log("DRAFTER:ERROR", "No active draft to finalize.")
        return None
    if CURRENT_TASK.get("status") != "waiting_review":
        log("DRAFTER:ERROR", f"Draft status is '{CURRENT_TASK.get('status')}', not 'waiting_review'.")
        return None

    file_path = Path(CURRENT_TASK["file_path"])
    if not file_path.exists():
        log("DRAFTER:ERROR", f"Draft file not found: {file_path}")
        return None

    content = file_path.read_text(encoding="utf-8")
    draft_type = CURRENT_TASK["type"]

    if draft_type == "email":
        result = {
            "type": "send_email",
            "content": content,
            "subject": CURRENT_TASK["metadata"].get("subject", ""),
            "file_path": str(file_path),
        }
    else:
        result = {
            "type": "report_ready",
            "content": content,
            "title": CURRENT_TASK["metadata"].get("title", ""),
            "file_path": str(file_path),
        }

    CURRENT_TASK["status"] = "completed"
    log("DRAFTER", f"Draft finalized. Type: {result['type']}")
    return result


# ── Test block ───────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  Drafter Agent — Test Run")
    print("=" * 50)

    # Simulate email draft
    print("\n--- Creating email draft ---")
    create_draft(
        "Write an email to my professor Dr. Smith about requesting "
        "a deadline extension for the AI project.",
        draft_type="email",
    )
    print(f"\nCURRENT_TASK: {CURRENT_TASK}")

    # Simulate finalization
    print("\n--- Finalizing draft ---")
    output = finalize_draft()
    print(f"\nFinalized output: {output}")
    print(f"CURRENT_TASK status: {CURRENT_TASK['status']}")
