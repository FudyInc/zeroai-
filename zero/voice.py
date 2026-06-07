"""Voice (TTS) via ElevenLabs — turn an outreach script into spoken audio.

Division of labor: ZERO's LLM writes WHAT to say (OUTREACH); ElevenLabs decides
HOW it sounds (your cloned voice). This module is the thin boundary to that
external service — stdlib only, no extra install.

It needs YOUR credentials (the cloning + the account are yours, not Claude's):
  - env ELEVENLABS_API_KEY : your ElevenLabs API key
  - voice_id               : the id of your cloned Chilean voice (see docs/voice.md)

    from zero.voice import speak
    speak("Hola, soy Fernanda de ZeroAI...", voice_id="abc123", out="hola.mp3")

CLI:
    python3 -m zero.voice --voices                       # list your voices + ids
    python3 -m zero.voice --voice-id abc123 --text "Hola..." --out hola.mp3
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

from ._env import load_env

load_env()   # pick up ELEVENLABS_API_KEY from .env if present

_BASE = "https://api.elevenlabs.io/v1"
# Multilingual model speaks natural Spanish; the *accent* comes from the voice,
# not the model — so pair it with a cloned Chilean voice for the ABC1 sound.
DEFAULT_MODEL = "eleven_multilingual_v2"


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
    args = p.parse_args(argv)

    if args.voices:
        for vid, name in list_voices():
            print(f"  {vid}  ·  {name}")
        return 0
    if not (args.voice_id and args.text):
        p.error("usá --voices, o --voice-id y --text juntos")
    path = speak(args.text, args.voice_id, out=args.out,
                 stability=args.stability, similarity_boost=args.similarity)
    print(f"✓ audio escrito en {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
