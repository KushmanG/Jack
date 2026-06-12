# 🎙️ Voice Input Agent

A minimal, local voice-controlled input agent for macOS (Apple Silicon).  
Listens for a wake word, transcribes speech, parses intent, and dispatches to stub agents.

## Quick Start

```bash
# 1. Activate the project venv
source Jarvis/bin/activate

# 2. Install dependencies
pip install -r voice_agent/requirements.txt

# 3. Run the agent
python voice_agent/main.py
```

## Usage

1. The agent starts in **passive listening** mode  
2. Say **"hey nari"** (configurable in `main.py`)  
3. After detection, you have **~7 seconds** to speak your command  
4. The agent transcribes → parses intent → dispatches → logs the result  
5. After a 2s cooldown, it returns to passive listening  

### Supported Intents

| Say something like…               | Intent      | Agent            |
| --------------------------------- | ----------- | ---------------- |
| "send emails to founders"         | `outreach`  | `outreach_agent` |
| "schedule a meeting tomorrow"     | `calendar`  | `calendar_agent` |
| anything else                     | `unknown`   | *(logged only)*  |

## Terminal Output

```
[LISTENING] Waiting for "hey nari"…
[WAKE] Detected!
[RECORDING] 7s — speak now…
[TRANSCRIPTION] "schedule a meeting tomorrow"
[INTENT] calendar
[DISPATCH] → calendar_agent
[AGENT:CALENDAR] Would process: 'schedule a meeting tomorrow'
[RESPONSE] Done.
[COOLDOWN] 2s…
```

## Configuration

Edit the constants at the top of `main.py`:

| Constant         | Default      | Description                              |
| ---------------- | ------------ | ---------------------------------------- |
| `WAKE_WORD`      | `"hey nari"` | Wake phrase to listen for                |
| `RECORD_DURATION`| `7`          | Seconds of active recording after wake   |
| `COOLDOWN`       | `2`          | Seconds before re-arming after dispatch  |
| `WAKE_CHUNK`     | `2`          | Seconds per wake-word scan chunk         |

## Apple Silicon Notes

- **faster-whisper** uses `ctranslate2` under the hood. The `int8` compute type is used for CPU inference, which works well on Apple Silicon.
- The whisper `base` model (~150 MB) is auto-downloaded on first run to `~/.cache/huggingface/`.
- **sounddevice** uses the system's default microphone. Grant Terminal/IDE microphone access in **System Settings → Privacy & Security → Microphone**.
- **pyttsx3** uses macOS's built-in `NSSpeechSynthesizer` — no extra setup needed.

## Project Structure

```
voice_agent/
├── main.py            # Wake loop + orchestration
├── agents.py          # Stub agents + intent parser
├── utils.py           # Audio recording, transcription, TTS
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

## Extending

- **Add a new intent:** Add keywords to `_INTENT_MAP` in `agents.py`  
- **Add a new agent:** Write a function, add it to `_AGENTS` dict in `agents.py`  
- **Swap wake word engine:** Replace `detect_wake_word()` in `main.py` with Vosk or another engine  
- **Connect real APIs:** Replace the stub functions in `agents.py` with actual API calls  
