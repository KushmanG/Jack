"""Audio helpers and transcription utilities."""

import os
import numpy as np
import sounddevice as sd

# ── Globals ──────────────────────────────────────────────────────────
# Lightweight model — used for idle wake-word scanning (fast, low CPU)
WAKE_MODEL   = "mlx-community/whisper-base-mlx"
# High-accuracy model — used for active listening after wake
ACTIVE_MODEL = "mlx-community/whisper-large-v3-mlx"
SAMPLE_RATE  = 16000



def log(tag: str, msg: str = ""):
    """Formatted log: [TAG] message"""
    print(f"[{tag}] {msg}", flush=True)


# ── Audio ────────────────────────────────────────────────────────────
def record_chunk(duration: float = 7.0) -> np.ndarray:
    """Record a fixed-length audio chunk (16 kHz, mono, float32)."""
    log("RECORDING", f"{duration}s — speak now…")
    audio = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    return audio.flatten()


def record_short(duration: float = 2.0) -> np.ndarray:
    """Record a short chunk for wake-word scanning."""
    # Retry mechanism for macOS PortAudio hiccups
    for attempt in range(3):
        try:
            audio = sd.rec(
                int(duration * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
            )
            sd.wait()
            return audio.flatten()
        except sd.PortAudioError as e:
            if attempt < 2:
                import time
                time.sleep(0.5)  # Let macOS audio subsystem recover
            else:
                log("AUDIO:ERROR", f"Recording failed completely: {e}")
                return np.zeros(0, dtype="float32")


def record_until_silence(
    silence_threshold: float = 0.015,
    silence_duration: float = 7.0,
    frame_ms: int = 200,
) -> np.ndarray:
    """
    Record until SILENCE_DURATION seconds of genuine silence passes.

    Uses RMS energy per frame to distinguish:
      - Speech / loud sounds  → keep listening
      - Breathing / humming   → NOT silence (above threshold if audible)
      - True silence          → increment silence counter

    silence_threshold: RMS below this = silence (tune if needed, default 0.015)
    silence_duration : stop after this many seconds of continuous silence (default 7s)
    frame_ms         : analysis frame size in milliseconds (default 200ms)
    """
    import time

    frame_size   = int(SAMPLE_RATE * frame_ms / 1000)
    silent_frames_needed = int(silence_duration * 1000 / frame_ms)

    frames: list[np.ndarray] = []
    silent_count = 0
    speech_detected = False  # Don't stop on silence before any speech

    log("VAD", f"Listening… (stops after {silence_duration}s of silence)")

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
        while True:
            frame, _ = stream.read(frame_size)
            frame = frame.flatten()
            frames.append(frame)

            rms = float(np.sqrt(np.mean(frame ** 2)))

            if rms > silence_threshold:
                speech_detected = True
                silent_count = 0  # Reset silence counter on any sound
            else:
                if speech_detected:   # Only count silence AFTER speech starts
                    silent_count += 1

            if speech_detected and silent_count >= silent_frames_needed:
                log("VAD", "Silence detected — done listening.")
                break

    return np.concatenate(frames) if frames else np.zeros(0, dtype="float32")


# ── Whisper (mlx-whisper — Apple Silicon native) ─────────────────────
# Resolved local cache paths — populated once by load_whisper_model()
_wake_path:   str | None = None
_active_path: str | None = None


def load_whisper_model():
    """Resolve both models to local cache paths (downloads on first run).
    All subsequent transcribe() calls use the local path — no HF network calls.
    """
    global _wake_path, _active_path
    from huggingface_hub import snapshot_download
    import mlx_whisper

    log("MODEL", f"Resolving wake model  : {WAKE_MODEL}…")
    _wake_path = snapshot_download(repo_id=WAKE_MODEL)
    log("MODEL", f"Wake model ready  → {_wake_path}")

    log("MODEL", f"Resolving active model: {ACTIVE_MODEL} (first run ~1.5 GB)…")
    _active_path = snapshot_download(repo_id=ACTIVE_MODEL)
    log("MODEL", f"Active model ready → {_active_path}")

    # Warm up both so first real inference isn't slow
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    mlx_whisper.transcribe(silence, path_or_hf_repo=_wake_path)
    mlx_whisper.transcribe(silence, path_or_hf_repo=_active_path)
    log("MODEL", "Both models warmed up.")


def transcribe(audio: np.ndarray, model: str = "wake") -> str:
    """Transcribe audio array → string using mlx-whisper (local path, no network).

    Args:
        audio: 16 kHz float32 numpy array
        model: "wake" (default) or "active"
    """
    import mlx_whisper
    path = _active_path if model == "active" else _wake_path
    if path is None:
        raise RuntimeError("Call load_whisper_model() before transcribe().")
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=path, language="en")
    return result.get("text", "").strip()



# ── TTS — Kokoro ONNX (human male voice) ────────────────────────────
_kokoro = None  # lazy-loaded on first speak()

# Cache dir for downloaded model files
_KOKORO_CACHE = os.path.expanduser("~/.cache/kokoro-onnx")
_MODEL_URL  = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"


def _download(url: str, dest: str):
    """Download url → dest with a simple progress log."""
    import urllib.request
    filename = os.path.basename(dest)
    log("TTS", f"Downloading {filename}…")
    urllib.request.urlretrieve(url, dest)
    log("TTS", f"{filename} ready.")


def _load_kokoro():
    """Download & cache Kokoro model files, then init Kokoro."""
    global _kokoro
    if _kokoro is not None:
        return _kokoro
    from kokoro_onnx import Kokoro

    os.makedirs(_KOKORO_CACHE, exist_ok=True)
    model_path  = os.path.join(_KOKORO_CACHE, "kokoro-v1.0.onnx")
    voices_path = os.path.join(_KOKORO_CACHE, "voices-v1.0.bin")

    if not os.path.exists(model_path):
        log("TTS", "First run — downloading Kokoro model (~310 MB)…")
        _download(_MODEL_URL, model_path)
    if not os.path.exists(voices_path):
        log("TTS", "First run — downloading voices (~450 MB)…")
        _download(_VOICES_URL, voices_path)

    _kokoro = Kokoro(model_path, voices_path)
    log("TTS", "Kokoro ready.")
    return _kokoro


def speak(text: str):
    """Speak text using Kokoro (human male voice). Falls back to macOS say."""
    try:
        k = _load_kokoro()
        samples, sr = k.create(text, voice="am_michael", speed=1.0, lang="en-us")
        import sounddevice as sd
        import time
        sd.play(samples, int(sr))
        sd.wait()
        sd.stop()         # Explicitly kill the stream
        time.sleep(0.3)   # Hardware release delay
    except Exception as e:
        log("TTS:WARN", f"Kokoro failed ({e}), falling back to say…")
        try:
            import subprocess
            subprocess.run(["say", "-v", "Daniel", text], check=False)
        except Exception:
            pass  # TTS is optional; never crash the agent
