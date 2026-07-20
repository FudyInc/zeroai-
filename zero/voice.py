"""Voice (TTS) via ElevenLabs — turn an outreach script into spoken audio.

Division of labor: ZERO's LLM writes WHAT to say (OUTREACH); ElevenLabs decides
HOW it sounds (your cloned voice). This module is the thin boundary to that
external service — stdlib only, no extra install.

It needs YOUR credentials (the cloning + the account are yours, not Claude's):
  - env ELEVENLABS_API_KEY : your ElevenLabs API key
  - voice_id               : the id of your cloned Chilean voice (see docs/voice.md)

    from zero.voice import speak
    speak("Hola, soy Fernanda de ZeroAI...", voice_id="abc123", out="hola.mp3")

    from zero.voice import speak_with_typing
    speak_with_typing("Dame un segundo... encontré 12 leads para tu ICP.",
                       voice_id="abc123", out="respuesta.wav")   # antepone teclado sintético

CLI:
    python3 -m zero.voice --voices                       # list your voices + ids
    python3 -m zero.voice --voice-id abc123 --text "Hola..." --out hola.mp3
    python3 -m zero.voice --voice-id abc123 --text "Dame un segundo..." --out r.wav --typing
"""
from __future__ import annotations

import json
import math
import os
import random
import struct
import urllib.error
import urllib.request
import wave
from typing import List, Optional, Tuple

from ._env import load_env

load_env()   # pick up ELEVENLABS_API_KEY from .env if present

_BASE = "https://api.elevenlabs.io/v1"
# Multilingual model speaks natural Spanish; the *accent* comes from the voice,
# not the model — so pair it with a cloned Chilean voice for the ABC1 sound.
DEFAULT_MODEL = "eleven_multilingual_v2"
# Sample rate for the "typing" path (speak_with_typing / _speak_pcm). Fixed so the
# synthetic keyboard clip and the ElevenLabs speech share one rate and can be
# concatenated as raw PCM — no external mixer (ffmpeg/pydub) needed.
_TYPING_SAMPLE_RATE = 16000


def _key(api_key: Optional[str]) -> str:
    key = api_key or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError(
            "Falta ELEVENLABS_API_KEY. Conseguila en ElevenLabs (Profile → API Keys) "
            "y exportala: export ELEVENLABS_API_KEY=..."
        )
    return key


def list_voices(api_key: Optional[str] = None) -> List[Tuple[str, str]]:
    """Return [(voice_id, name)] for the voices in your account (incl. clones)."""
    req = urllib.request.Request(f"{_BASE}/voices", headers={"xi-api-key": _key(api_key)})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ElevenLabs respondió {e.code}: {e.read().decode('utf-8', 'replace')}") from e
    return [(v["voice_id"], v["name"]) for v in data.get("voices", [])]


def speak(
    text: str,
    voice_id: str,
    out: str = "out.mp3",
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    stability: float = 0.5,
    similarity_boost: float = 0.8,
) -> str:
    """Synthesize `text` with your cloned voice and write an MP3 to `out`."""
    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": stability, "similarity_boost": similarity_boost},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{_BASE}/text-to-speech/{voice_id}",
        data=body,
        headers={"xi-api-key": _key(api_key), "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ElevenLabs respondió {e.code}: {e.read().decode('utf-8', 'replace')}") from e
    with open(out, "wb") as fh:
        fh.write(audio)
    return out


def _synthetic_typing_pcm(duration: float = 1.4, sample_rate: int = _TYPING_SAMPLE_RATE,
                           seed: Optional[int] = None) -> bytes:
    """A short burst of synthetic keyboard-click noise as 16-bit PCM (mono).

    TODO(asset real): esto es un placeholder sintético — sonido de teclado real
    grabado (ver docs/voice.md) sonaría mejor. Sirve para no bloquear el efecto en
    conseguir un archivo de audio.

    Irregular gaps between clicks (not a steady metronome tic) + an exponentially
    decaying noise burst per click, so it reads as a person typing rather than a
    beep. Deterministic if `seed` is given (useful for tests).
    """
    rng = random.Random(seed)
    n_samples = max(1, int(duration * sample_rate))
    samples = [0] * n_samples
    click_len = max(1, int(0.012 * sample_rate))  # ~12ms per keystroke
    t = 0
    while t < n_samples - click_len:
        t += int(rng.uniform(0.06, 0.16) * sample_rate)  # gap before next keystroke
        if t >= n_samples - click_len:
            break
        for i in range(click_len):
            decay = math.exp(-i / (click_len * 0.3))
            samples[t + i] = int(rng.uniform(-1, 1) * decay * 6000)  # quiet, subtle
        t += click_len
    return struct.pack(f"<{n_samples}h", *samples)


def _speak_pcm(
    text: str,
    voice_id: str,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    stability: float = 0.5,
    similarity_boost: float = 0.8,
    sample_rate: int = _TYPING_SAMPLE_RATE,
) -> bytes:
    """Like speak(), but returns raw 16-bit PCM bytes instead of writing an MP3.

    Internal helper for speak_with_typing(): PCM lets us concatenate the synthetic
    keyboard clip and the ElevenLabs speech as raw samples, then wrap them in one
    WAV file with the stdlib `wave` module — no ffmpeg/pydub required.
    """
    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": stability, "similarity_boost": similarity_boost},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{_BASE}/text-to-speech/{voice_id}?output_format=pcm_{sample_rate}",
        data=body,
        headers={"xi-api-key": _key(api_key), "Content-Type": "application/json", "Accept": "audio/pcm"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ElevenLabs respondió {e.code}: {e.read().decode('utf-8', 'replace')}") from e


def speak_with_typing(
    text: str,
    voice_id: str,
    out: str = "out.wav",
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    stability: float = 0.5,
    similarity_boost: float = 0.8,
    typing_seconds: float = 1.4,
) -> str:
    """Like speak(), but prepends a short synthetic keyboard-click clip.

    Realism for the moments the agent is "looking something up" before answering —
    e.g. a question that needs a real lookup mid-call. NOT meant for every turn;
    call this only for that specific pause, plain speak() otherwise (see module
    docstring / prompts/francisca or fernanda persona for when that applies).

    Writes a WAV (not MP3): the typing clip + ElevenLabs speech are concatenated as
    raw PCM (see _speak_pcm), which pure stdlib can wrap into a WAV but not encode
    as MP3.
    """
    typing_pcm = _synthetic_typing_pcm(typing_seconds, _TYPING_SAMPLE_RATE)
    speech_pcm = _speak_pcm(text, voice_id, api_key=api_key, model=model,
                             stability=stability, similarity_boost=similarity_boost,
                             sample_rate=_TYPING_SAMPLE_RATE)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_TYPING_SAMPLE_RATE)
        w.writeframes(typing_pcm)
        w.writeframes(speech_pcm)
    return out


def _main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="ZERO · voz (ElevenLabs)")
    p.add_argument("--voices", action="store_true", help="listar tus voces y sus ids")
    p.add_argument("--voice-id", help="id de la voz (tu clon)")
    p.add_argument("--text", help="texto a decir")
    p.add_argument("--out", default="out.mp3", help="archivo de salida (mp3)")
    p.add_argument("--stability", type=float, default=0.5,
                   help="0–1; más bajo = más expresivo/variable (default 0.5)")
    p.add_argument("--similarity", type=float, default=0.8,
                   help="0–1; más alto = más pegado a la voz/acento clonado (default 0.8)")
    p.add_argument("--typing", action="store_true",
                   help="antepone un clip sintético de teclado (usa --out con .wav)")
    p.add_argument("--typing-seconds", type=float, default=1.4,
                   help="duración del clip de teclado si --typing (default 1.4s)")
    args = p.parse_args(argv)

    if args.voices:
        for vid, name in list_voices():
            print(f"  {vid}  ·  {name}")
        return 0
    if not (args.voice_id and args.text):
        p.error("usá --voices, o --voice-id y --text juntos")
    if args.typing:
        path = speak_with_typing(args.text, args.voice_id, out=args.out,
                                  stability=args.stability, similarity_boost=args.similarity,
                                  typing_seconds=args.typing_seconds)
    else:
        path = speak(args.text, args.voice_id, out=args.out,
                     stability=args.stability, similarity_boost=args.similarity)
    print(f"✓ audio escrito en {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
