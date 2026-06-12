#!/usr/bin/env python3
"""Voice Input Agent — wake loop + orchestration."""

import sys
import time
import random

from utils import log, record_short, transcribe, speak, load_whisper_model
from agents import confirm_loop, dispatch, has_paused_plan, resume_loop
from config import require_api_key


# ── Configuration ────────────────────────────────────────────────────
WAKE_WORD    = "Jack"               # wake word to arm the agent
END_COMMAND  = "over and out" # phrase to stop listening and dispatch
COOLDOWN     = 2                     # seconds before re-arming after dispatch
WAKE_CHUNK   = 2                     # seconds per chunk during wake scanning
ACTIVE_CHUNK = 8                     # seconds per chunk during active listening
                                      # (8s amortizes whisper-large inference cost)


def detect_wake_word() -> bool:
    """
    Continuously record short chunks and transcribe them,
    looking for the wake word substring. Returns True on detection.
    """
    while True:
        audio = record_short(WAKE_CHUNK)
        text = transcribe(audio).lower()
        # Fuzzy match: check if wake word tokens appear in transcript
        wake_tokens = WAKE_WORD.lower().split()
        if all(tok in text for tok in wake_tokens):
            return True


def listen_until_done() -> str:
    """
    Record ACTIVE_CHUNK-second clips indefinitely, accumulating transcript,
    until END_COMMAND tokens appear. No timeout — runs until you say the phrase.
    Returns the full transcript with the end command stripped out.
    """
    log("ACTIVE", f'Listening… say "{END_COMMAND.title()}" when done')
    parts: list[str] = []

    while True:
        audio = record_short(ACTIVE_CHUNK)
        chunk_text = transcribe(audio, model="active")
        if chunk_text:
            log("CHUNK", f'"{chunk_text}"')
            parts.append(chunk_text)

        # Check accumulated transcript for end command
        full = " ".join(parts).lower()
        end_tokens = END_COMMAND.lower().split()
        if all(tok in full for tok in end_tokens):
            log("END", f'"{END_COMMAND}" detected — stopping.')
            break

    # Strip the end command phrase from the final text
    raw = " ".join(parts)
    clean = raw.lower().replace(END_COMMAND.lower(), "").strip(" ,.").strip()
    return clean


def main():
    """Main loop: listen → wake → record → transcribe → dispatch → repeat."""
    print("=" * 52)
    print("  🎙️  Voice Input Agent")
    print(f"  Wake word   : \"{WAKE_WORD}\"")
    print(f"  End command : \"{END_COMMAND}\"")
    print("  Say the wake word to begin. Ctrl+C to exit.")
    print("=" * 52)
    print()

    # Pre-checks
    require_api_key()

    # Pre-load whisper so first wake isn't slow
    print("[STARTUP] Loading models — this may take a moment on first run…")
    load_whisper_model()
    print()
    print("=" * 52)
    print(f"  🟢  READY — say \"{WAKE_WORD}\" to begin, \"{END_COMMAND}\" to stop")
    print("=" * 52)
    print()

    while True:
        try:
            # Step 1 — Passive listening
            log("LISTENING", f"Waiting for \"{WAKE_WORD}\"…")
            detect_wake_word()

            # Step 2 — Wake detected
            log("WAKE", "Detected!")
            speak(random.choice(["Here.", "Listening.", "Mhm."]))

            # Step 3 — Resume paused plan OR record fresh speech
            if has_paused_plan():
                plan = resume_loop()
                if plan is None:
                    log("RESPONSE", "Paused again. Going back to sleep.")
                    continue
            else:
                # Normal flow: open-ended recording until end command
                text = listen_until_done()
                log("TRANSCRIPTION", f'"{text}"')

                if not text.strip():
                    log("RESPONSE", "No speech detected. Going back to sleep.")
                    continue

                # Step 4 — LLM confirmation loop
                plan = confirm_loop(text)
                if plan is None:
                    log("RESPONSE", "Paused or could not confirm. Going back to sleep.")
                    continue

            # Step 5 — Dispatch
            dispatch(plan)

            # Step 6 — Feedback
            log("RESPONSE", "Done.")
            speak("Done.")

            # Cooldown before re-arming
            log("COOLDOWN", f"{COOLDOWN}s…")
            time.sleep(COOLDOWN)
            print()

        except KeyboardInterrupt:
            print("\n")
            log("EXIT", "Shutting down. Goodbye! 👋")
            sys.exit(0)


if __name__ == "__main__":
    main()
