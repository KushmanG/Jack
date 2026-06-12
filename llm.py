"""OpenRouter LLM client — interpret and clarify user commands."""

import json
import requests
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_URL
from utils import log


# ── System prompt ────────────────────────────────────────────────────
_SYSTEM = """\
You are a voice assistant's understanding engine. The user gives you a
spoken command (transcribed by Whisper — may contain minor errors).

Respond with ONLY valid JSON (no markdown, no backticks) with these keys:
{
  "understood": "<1-2 sentence plain-English summary of what the user wants>",
  "intent": "<one-word category: outreach | draft | plan | calendar | research | reminder | unknown>",
  "next_steps": ["<step 1>", "<step 2>", "..."]
}

Be concise. Infer intent from context even if the phrasing is unusual.
If you genuinely cannot determine intent, set intent to "unknown".
"""

_CLARIFY_SYSTEM = """\
You are a voice assistant's understanding engine. The user previously
gave a command and you produced an interpretation. The user has now
corrected or clarified their request.

Given:
- Your previous understanding (JSON)
- The user's correction (plain text)

Produce an UPDATED JSON with the same keys:
{
  "understood": "<updated summary>",
  "intent": "<updated intent>",
  "next_steps": ["<updated steps>"]
}

Respond with ONLY valid JSON (no markdown, no backticks).
"""


# ── API helper ───────────────────────────────────────────────────────
def _call(messages: list[dict]) -> dict:
    """Send messages to OpenRouter, return parsed JSON dict."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.3,
    }

    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
    if not resp.ok:
        log("LLM:ERROR", f"HTTP {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    # Strip markdown fences if the model wraps them anyway
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0]
    return json.loads(content)


# ── Public API ───────────────────────────────────────────────────────
def interpret(transcript: str) -> dict:
    """First-pass interpretation of a raw transcript → plan dict."""
    log("LLM", f"Interpreting: \"{transcript}\"")
    result = _call([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": transcript},
    ])
    log("LLM", f"Understood: {result.get('understood', '?')}")
    return result


def clarify(previous: dict, correction: str) -> dict:
    """Re-interpret based on user correction → updated plan dict."""
    log("LLM", f"Clarifying with: \"{correction}\"")
    result = _call([
        {"role": "system", "content": _CLARIFY_SYSTEM},
        {"role": "user", "content": (
            f"Previous understanding:\n{json.dumps(previous, indent=2)}\n\n"
            f"User's correction:\n{correction}"
        )},
    ])
    log("LLM", f"Updated: {result.get('understood', '?')}")
    return result


def generate_with_llm(prompt: str) -> str:
    """Send a freeform prompt, return raw text response (not JSON)."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
    }
    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
    if not resp.ok:
        log("LLM:ERROR", f"HTTP {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    return content.strip()
