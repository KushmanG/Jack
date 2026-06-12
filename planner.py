"""Socratic Conversational Planner Agent.

Multi-turn voice conversation that questions, refines, extracts tasks,
and compiles a structured plan. Feels like a sharp strategist, not a chatbot.
"""

import json
import subprocess
from pathlib import Path

from llm import generate_with_llm
from utils import log, speak, record_until_silence, transcribe

# ── State ────────────────────────────────────────────────────────────
PLANNER_MEMORY: list[dict] = []   # {"role": "user"|"jack", "text": "..."}
TASK_BUFFER: list[dict] = []      # {"task": "...", "owner": "agent"|"user"}
_obedient_mode: bool = False

_PROJECT_ROOT = Path(__file__).parent
# VAD settings for planner conversation turns
SILENCE_THRESHOLD = 0.015  # RMS below this = silence (adjust if mic is sensitive)
SILENCE_WAIT      = 7.0    # seconds of silence before Jack responds

# ── Override / End detection ─────────────────────────────────────────
_OBEDIENCE_PHRASES = {
    "don't ask why", "just do it", "just compile", "no questions",
    "stop questioning", "don't question", "just get it done",
    "skip the questions", "enough questions",
}

_END_PHRASES = {
    "done", "that's it", "compile it", "compile", "go ahead",
    "execute", "that's all", "wrap it up", "finalize",
}


def _detect_obedience(text: str) -> bool:
    lower = text.lower().strip(" .,!?")
    for phrase in _OBEDIENCE_PHRASES:
        if phrase in lower:
            return True
    return False


def _detect_end(text: str) -> bool:
    lower = text.lower().strip(" .,!?")
    for phrase in _END_PHRASES:
        if phrase in lower:
            return True
    return False


# ── Socratic system prompt ───────────────────────────────────────────
_SOCRATIC_SYSTEM = """\
You are a sharp strategic thinking partner in a voice conversation.
Your job: understand what the user really wants, question vague ideas,
and silently extract actionable tasks.

Rules:
- Ask "why" when intent is unclear or important
- Challenge vague or weak ideas briefly
- Be concise and direct — this is voice, not text (1-2 short sentences max)
- NEVER say generic phrases like "That's a great idea!" or "Sure, I can help!"
- Silently extract tasks without mentioning them to the user
- Break complex ideas into actionable pieces internally

{mode_instruction}

Conversation so far:
{conversation}

Tasks extracted so far:
{tasks}

Respond with ONLY valid JSON (no markdown, no backticks):
{{
  "response": "<what to say to user — 1-2 short sentences, natural and direct>",
  "tasks_extracted": [{{"task": "...", "owner": "agent"}} or {{"task": "...", "owner": "user"}}],
  "done": false
}}

"tasks_extracted" should only contain NEW tasks from the latest user message.
Set "owner" to "agent" for automatable tasks (writing, emailing, drafting).
Set "owner" to "user" for decisions, research, or external actions.
"""

_COMPILE_SYSTEM = """\
Given this conversation and task list, produce a final structured plan.

CRITICAL RULES:
- Deduplicate similar tasks (merge "promote project" + "advertise project" into one)
- Split tasks into agent-automatable vs user-required
- Summary should be concise (2-3 sentences max)
- Tasks must be specific and actionable (not vague)

Conversation:
{conversation}

All extracted tasks:
{tasks}

Respond with ONLY valid JSON (no markdown, no backticks):
{{
  "summary": "<concise 2-3 sentence summary of what was discussed and decided>",
  "tasks_for_agents": ["<specific actionable task>", "..."],
  "tasks_for_user": ["<specific actionable task>", "..."]
}}
"""


# ── Core conversation loop ───────────────────────────────────────────
def _format_conversation() -> str:
    lines = []
    for turn in PLANNER_MEMORY:
        prefix = "User" if turn["role"] == "user" else "Jack"
        lines.append(f"{prefix}: {turn['text']}")
    return "\n".join(lines) if lines else "(conversation just started)"


def _format_tasks() -> str:
    if not TASK_BUFFER:
        return "(none yet)"
    return "\n".join(
        f"- [{t['owner']}] {t['task']}" for t in TASK_BUFFER
    )


def _merge_tasks(new_tasks: list[dict]):
    """Add new tasks, deduplicating against existing buffer."""
    existing = {t["task"].lower().strip() for t in TASK_BUFFER}
    for t in new_tasks:
        task_text = t.get("task", "").strip()
        if task_text and task_text.lower() not in existing:
            TASK_BUFFER.append(t)
            existing.add(task_text.lower())


def _get_socratic_response(user_text: str) -> dict:
    """Send conversation to LLM, get Socratic response + extracted tasks."""
    PLANNER_MEMORY.append({"role": "user", "text": user_text})

    mode_instruction = (
        "OBEDIENT MODE: Stop questioning. Stop suggesting alternatives. "
        "Just help structure and finalize. Be agreeable and efficient."
        if _obedient_mode else
        "SOCRATIC MODE: Question unclear intent. Challenge vague ideas. "
        "Suggest better approaches when relevant."
    )

    prompt = _SOCRATIC_SYSTEM.format(
        mode_instruction=mode_instruction,
        conversation=_format_conversation(),
        tasks=_format_tasks(),
    )

    raw = generate_with_llm(prompt)

    # Parse JSON (strip markdown fences if LLM adds them)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        log("PLANNER:WARN", f"Bad JSON from LLM, using raw text as response")
        result = {"response": raw, "tasks_extracted": [], "done": False}

    return result


def _compile_plan() -> dict:
    """Final compilation: deduplicate, split, and structure the plan."""
    log("PLANNER", "Compiling final plan…")

    prompt = _COMPILE_SYSTEM.format(
        conversation=_format_conversation(),
        tasks=_format_tasks(),
    )

    raw = generate_with_llm(prompt)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        log("PLANNER:WARN", "Bad JSON from compile, building from buffer")
        result = {
            "summary": "Planning session completed.",
            "tasks_for_agents": [t["task"] for t in TASK_BUFFER if t["owner"] == "agent"],
            "tasks_for_user": [t["task"] for t in TASK_BUFFER if t["owner"] == "user"],
        }

    return result


def _save_plan(plan: dict):
    """Save plan to Drafts/Plans/ and open in VS Code."""
    folder = _PROJECT_ROOT / "Drafts" / "Plans"
    folder.mkdir(parents=True, exist_ok=True)

    # Generate filename
    filename_raw = generate_with_llm(
        f"Give a short 2-4 word filename (no extension, no spaces, use underscores) "
        f"for this plan:\n{plan.get('summary', 'plan')}\n\n"
        f"Respond with ONLY the filename, nothing else."
    )
    filename = filename_raw.strip().strip("\"'").replace(" ", "_")
    if filename.endswith(".txt"):
        filename = filename[:-4]
    filename = filename + ".txt"

    # Format content
    agent_tasks = plan.get("tasks_for_agents", [])
    user_tasks = plan.get("tasks_for_user", [])

    lines = ["— PLAN —", ""]
    lines.append(f"Summary:\n{plan.get('summary', '')}")
    lines.append("")
    lines.append("Tasks I'll manage:")
    for i, t in enumerate(agent_tasks, 1):
        lines.append(f"  {i}. {t}")
    lines.append("")
    lines.append("Your Tasks:")
    for i, t in enumerate(user_tasks, 1):
        lines.append(f"  {i}. {t}")
    lines.append("")
    lines.append("— END —")

    file_path = folder / filename
    file_path.write_text("\n".join(lines), encoding="utf-8")
    log("PLANNER", f"Saved: {file_path}")

    try:
        subprocess.run(["code", str(file_path)], check=False)
        log("PLANNER", "Opened in VS Code.")
    except FileNotFoundError:
        log("PLANNER:WARN", "'code' not found — skipping VS Code.")

    return str(file_path)


# ── Main entry point ─────────────────────────────────────────────────
def run_planner(initial_input: str):
    """Run the full Socratic planning conversation."""
    global _obedient_mode

    # Reset state for new session
    PLANNER_MEMORY.clear()
    TASK_BUFFER.clear()
    _obedient_mode = False

    log("PLANNER", "📋 Entering planning mode…")
    speak("Alright, let's think this through.")

    # First turn — process the initial input
    result = _get_socratic_response(initial_input)
    _merge_tasks(result.get("tasks_extracted", []))

    response_text = result.get("response", "Tell me more.")
    PLANNER_MEMORY.append({"role": "jack", "text": response_text})
    log("PLANNER:JACK", f'"{response_text}"')
    speak(response_text)

    # Multi-turn conversation loop
    while True:
        # Record user's response
        audio = record_until_silence(
            silence_threshold=SILENCE_THRESHOLD,
            silence_duration=SILENCE_WAIT,
        )
        user_text = transcribe(audio, model="active")

        if not user_text.strip():
            continue  # silence, keep listening

        log("PLANNER:USER", f'"{user_text}"')

        # Check for obedience override
        if _detect_obedience(user_text):
            _obedient_mode = True
            log("PLANNER", "⚡ Obedience mode activated — no more questions.")
            speak("Got it. No more questions.")
            # Still process this turn for any task content
            result = _get_socratic_response(user_text)
            _merge_tasks(result.get("tasks_extracted", []))
            response_text = result.get("response", "Understood.")
            PLANNER_MEMORY.append({"role": "jack", "text": response_text})
            log("PLANNER:JACK", f'"{response_text}"')
            speak(response_text)
            continue

        # Check for end condition
        if _detect_end(user_text):
            log("PLANNER", "🏁 End condition detected — compiling plan.")
            speak("Got it. Let me compile everything.")
            break

        # Normal turn — get Socratic response
        result = _get_socratic_response(user_text)
        _merge_tasks(result.get("tasks_extracted", []))

        response_text = result.get("response", "Tell me more.")
        PLANNER_MEMORY.append({"role": "jack", "text": response_text})
        log("PLANNER:JACK", f'"{response_text}"')
        speak(response_text)

    # Compile and save
    plan = _compile_plan()
    file_path = _save_plan(plan)

    # Speak summary
    summary = plan.get("summary", "Plan compiled.")
    agent_count = len(plan.get("tasks_for_agents", []))
    user_count = len(plan.get("tasks_for_user", []))
    speak(
        f"{summary} "
        f"I've got {agent_count} tasks to handle, and {user_count} for you. "
        f"Check the file I just opened."
    )

    log("PLANNER", f"✅ Planning complete. File: {file_path}")
    log("PLANNER", f"Agent tasks: {agent_count}, User tasks: {user_count}")


# ── Test block ───────────────────────────────────────────────────────
if __name__ == "__main__":
    # Standalone test (simulates without voice — just prints prompts)
    print("=" * 50)
    print("  Socratic Planner — Test Mode (text input)")
    print("  Type 'done' to compile the plan.")
    print("=" * 50)

    # Override speak/record/transcribe for text-mode testing
    import utils
    utils.speak = lambda text: print(f"  🗣️  Jack: {text}")

    initial = input("\n🎤 You: ")
    PLANNER_MEMORY.clear()
    TASK_BUFFER.clear()

    result = _get_socratic_response(initial)
    _merge_tasks(result.get("tasks_extracted", []))
    response_text = result.get("response", "Tell me more.")
    PLANNER_MEMORY.append({"role": "jack", "text": response_text})
    print(f"  🗣️  Jack: {response_text}")

    while True:
        user_text = input("\n🎤 You: ")
        if _detect_end(user_text):
            break
        result = _get_socratic_response(user_text)
        _merge_tasks(result.get("tasks_extracted", []))
        response_text = result.get("response", "Tell me more.")
        PLANNER_MEMORY.append({"role": "jack", "text": response_text})
        print(f"  🗣️  Jack: {response_text}")

    print("\n⏳ Compiling plan…")
    plan = _compile_plan()
    print(f"\n📋 Final Plan:\n{json.dumps(plan, indent=2)}")
    print(f"\n📦 Task Buffer: {json.dumps(TASK_BUFFER, indent=2)}")
