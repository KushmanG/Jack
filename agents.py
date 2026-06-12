"""Agents, confirmation loop, and dispatcher."""

from utils import log, speak, record_short, transcribe
from llm import interpret, clarify

# ── Affirmation / Pause detection ───────────────────────────────────
_AFFIRM_WORDS = {
    "alright", "okay", "proceed", "yes", "do it", "go ahead",
    "confirmed", "correct", "that's right", "perfect", "go for it",
    "sounds good", "yep", "sure", "affirmative",
}

_PAUSE_WORDS = {
    "pause", "hold on", "wait", "stop", "hold up", "one moment",
    "one sec", "give me a sec", "give me a minute", "just a minute",
    "just a sec", "let me think", "hang on",
}

CONFIRM_CHUNK = 5  # seconds to listen for affirmation/correction

# Paused plan — persists until resumed or discarded
_paused_plan: dict | None = None


def _is_affirmation(text: str) -> bool:
    """Check if text is an affirmation (not a correction)."""
    lower = text.lower().strip(" .,!?")
    for phrase in _AFFIRM_WORDS:
        if phrase in lower:
            return True
    return False


def _is_pause(text: str) -> bool:
    """Check if text is a pause/hold-on command."""
    lower = text.lower().strip(" .,!?")
    for phrase in _PAUSE_WORDS:
        if phrase in lower:
            return True
    return False


def has_paused_plan() -> bool:
    """Return True if a plan is waiting to be resumed."""
    return _paused_plan is not None


def _format_plan(plan: dict) -> str:
    """Format plan dict into spoken/logged text."""
    understood = plan.get("understood", "I'm not sure what you want.")
    intent = plan.get("intent", "unknown")
    steps = plan.get("next_steps", [])

    lines = [f"I understood: {understood}"]
    lines.append(f"Intent: {intent}")
    if steps:
        lines.append("Next steps:")
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step}")
    return "\n".join(lines)


# ── Confirmation loop ────────────────────────────────────────────────
def confirm_loop(transcript: str) -> dict | None:
    """
    Send transcript to LLM → speak understanding → listen for
    affirmation or correction → loop until affirmed → return plan.
    """
    # First interpretation
    plan = interpret(transcript)
    log("PLAN", "\n" + _format_plan(plan))
    speak_text = (
        f"I understood: {plan.get('understood', '?')}. "
        f"Next steps: {', '.join(plan.get('next_steps', []))}. "
        f"Say alright to proceed, or tell me what I got wrong."
    )
    speak(speak_text)

    # Confirmation loop
    while True:
        log("CONFIRM", "Listening for affirmation, correction, or pause…")
        audio = record_short(CONFIRM_CHUNK)
        response = transcribe(audio, model="active")
        log("CONFIRM:HEARD", f'"{response}"')

        if not response.strip():
            log("CONFIRM", "No speech detected — listening again…")
            continue

        if _is_pause(response):
            global _paused_plan
            _paused_plan = plan
            log("CONFIRM", "⏸️  Paused. Call me when you're ready to resume.")
            speak("Got it. I'll hold on. Just call my name when you're ready.")
            return None  # signals main to go back to sleep

        if _is_affirmation(response):
            log("CONFIRM", "✅ Affirmed! Proceeding.")
            speak("Got it. Proceeding.")
            return plan

        # User is correcting — clarify with LLM
        log("CONFIRM", "Correction detected — re-interpreting…")
        plan = clarify(plan, response)
        log("PLAN", "\n" + _format_plan(plan))
        speak_text = (
            f"Updated understanding: {plan.get('understood', '?')}. "
            f"Next steps: {', '.join(plan.get('next_steps', []))}. "
            f"Say alright to proceed, or correct me again."
        )
        speak(speak_text)


# ── Resume loop ──────────────────────────────────────────────────────
def resume_loop() -> dict | None:
    """
    Called on wake when a paused plan exists.
    User can say 'proceed' to continue, or give corrections, or pause again.
    Returns confirmed plan, or None if paused/abandoned.
    """
    global _paused_plan
    plan = _paused_plan

    log("RESUME", "Paused plan found — resuming.")
    speak_text = (
        f"Welcome back. Last time I understood: {plan.get('understood', '?')}. "
        f"Say proceed to continue, give me corrections, or say pause to hold on again."
    )
    speak(speak_text)

    while True:
        log("CONFIRM", "Listening for proceed, correction, or pause…")
        audio = record_short(CONFIRM_CHUNK)
        response = transcribe(audio, model="active")
        log("CONFIRM:HEARD", f'"{response}"')

        if not response.strip():
            continue

        if _is_pause(response):
            log("CONFIRM", "⏸️  Paused again.")
            speak("Sure, I'll wait. Call me when you're ready.")
            return None  # keep _paused_plan intact, go back to sleep

        if _is_affirmation(response):
            log("CONFIRM", "✅ Proceeding with paused plan.")
            speak("Got it. Proceeding.")
            _paused_plan = None  # clear on successful resume
            return plan

        # Correction
        log("CONFIRM", "Correction detected — re-interpreting…")
        plan = clarify(plan, response)
        _paused_plan = plan  # keep updated in case they pause again
        log("PLAN", "\n" + _format_plan(plan))
        speak_text = (
            f"Updated: {plan.get('understood', '?')}. "
            f"Say proceed, or correct me again."
        )
        speak(speak_text)


# ── Stub agents ──────────────────────────────────────────────────────
def outreach_agent(plan: dict):
    """Stub: will be replaced with real email/outreach API."""
    log("AGENT:OUTREACH", f"Would execute plan: {plan}")


def calendar_agent(plan: dict):
    """Stub: will be replaced with real calendar API."""
    log("AGENT:CALENDAR", f"Would execute plan: {plan}")


def drafter_agent(plan: dict):
    """Draft emails or reports based on the plan."""
    from drafter import create_draft
    understood = plan.get("understood", "")
    steps_text = " ".join(plan.get("next_steps", []))
    combined = f"{understood} {steps_text}".lower()

    # Detect draft type from plan context
    if "report" in combined:
        draft_type = "report"
    else:
        draft_type = "email"

    log("AGENT:DRAFTER", f"Creating {draft_type} draft…")
    create_draft(understood, draft_type=draft_type)


def planner_agent(plan: dict):
    """Enter multi-turn Socratic planning conversation."""
    from planner import run_planner
    understood = plan.get("understood", "")
    log("AGENT:PLANNER", "Entering planning session…")
    run_planner(understood)


# ── Dispatcher ───────────────────────────────────────────────────────
_AGENTS = {
    "outreach": outreach_agent,
    "calendar": calendar_agent,
    "draft":    drafter_agent,
    "plan":     planner_agent,
}


def dispatch(plan: dict):
    """Route to the correct stub agent based on the LLM plan."""
    intent = plan.get("intent", "unknown")
    agent = _AGENTS.get(intent)
    if agent:
        log("DISPATCH", f"→ {agent.__name__} (intent: {intent})")
        agent(plan)
    else:
        log("DISPATCH", f"No agent for intent '{intent}'. Plan: {plan}")

