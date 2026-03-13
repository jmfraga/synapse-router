"""Audio endpoints: speech-to-text (transcription) and text-to-speech.

Compatible with OpenAI's audio API format:
- POST /v1/audio/transcriptions — STT via whisper-server (local) or cloud providers
- POST /v1/audio/speech — TTS via macOS `say` or cloud providers (ElevenLabs, OpenAI)
"""

import asyncio
import logging
import os
import tempfile
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.config import get_settings
from synapse.database import get_db
from synapse.models import ApiKey, UsageLog
from synapse.services.auth import authenticate

logger = logging.getLogger("synapse.audio")
router = APIRouter()

# --- Configuration ---

WHISPER_MODELS = {
    "whisper-large-v3": "/Users/jmfraga/models/whisper/ggml-large-v3.bin",
    "whisper-medium": "/Users/jmfraga/models/whisper/ggml-medium.bin",
    "whisper-base": "/Users/jmfraga/models/whisper/ggml-base.bin",
}
DEFAULT_WHISPER_MODEL = "whisper-large-v3"
WHISPER_SERVER_URL = "http://localhost:8178"

# macOS voices for TTS (Spanish-focused)
MACOS_VOICES = {
    "paulina": "Paulina",      # es-MX female
    "monica": "Mónica",        # es-ES female
    "jorge": "Jorge",          # es-ES male
    "juan": "Juan",            # es-MX male
    "allison": "Allison",      # en-US female
    "samantha": "Samantha",    # en-US female
    "tom": "Tom",              # en-US male
}
DEFAULT_VOICE = "paulina"


# --- Speech-to-Text (Transcription) ---

@router.post("/v1/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    model: str = Form(DEFAULT_WHISPER_MODEL),
    language: Optional[str] = Form(None),
    response_format: Optional[str] = Form("json"),
    api_key: ApiKey = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Transcribe audio to text using local whisper-server.

    Compatible with OpenAI's /v1/audio/transcriptions format.
    Models: whisper-large-v3, whisper-medium, whisper-base
    """
    start = time.monotonic()

    # Read uploaded file
    audio_data = await file.read()
    if not audio_data:
        raise HTTPException(400, "Empty audio file")

    # Forward to whisper-server
    lang = language or "es"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{WHISPER_SERVER_URL}/inference",
                files={"file": (file.filename or "audio.wav", audio_data, file.content_type or "audio/wav")},
                data={
                    "response_format": response_format or "json",
                    "language": lang,
                },
            )

        if resp.status_code != 200:
            raise HTTPException(502, f"Whisper server error: {resp.text}")

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Log usage
        log = UsageLog(
            api_key_id=api_key.id,
            provider="whisper-local",
            model=model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=elapsed_ms,
            cost_usd=0.0,
            status="success",
            route_path=f"whisper-local/{model}",
        )
        db.add(log)
        await db.commit()

        result = resp.json()
        return result

    except httpx.ConnectError:
        raise HTTPException(503, "Whisper server not available. Is it running on port 8178?")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(500, f"Transcription failed: {str(e)}")


# --- Text-to-Speech ---

class SpeechRequest(BaseModel):
    model: str = "tts-local"       # tts-local (macOS say) or future cloud models
    input: str                     # Text to speak
    voice: str = DEFAULT_VOICE     # Voice name
    response_format: str = "wav"   # wav, aiff
    speed: float = 1.0             # Speech rate multiplier


@router.post("/v1/audio/speech")
async def text_to_speech(
    request: SpeechRequest,
    api_key: ApiKey = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Generate speech from text using macOS `say` or cloud providers.

    Compatible with OpenAI's /v1/audio/speech format.
    Models: tts-local (macOS say)
    Voices: paulina, monica, jorge, juan, allison, samantha, tom
    """
    start = time.monotonic()

    if request.model == "tts-local":
        audio_data = await _tts_macos_say(request)
    else:
        raise HTTPException(400, f"Unknown TTS model: {request.model}. Available: tts-local")

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # Log usage
    log = UsageLog(
        api_key_id=api_key.id,
        provider="tts-local",
        model=request.model,
        prompt_tokens=len(request.input.split()),
        completion_tokens=0,
        total_tokens=len(request.input.split()),
        latency_ms=elapsed_ms,
        cost_usd=0.0,
        status="success",
        route_path=f"tts-local/{request.voice}",
    )
    db.add(log)
    await db.commit()

    content_type = "audio/wav" if request.response_format == "wav" else "audio/aiff"
    return Response(content=audio_data, media_type=content_type)


async def _tts_macos_say(request: SpeechRequest) -> bytes:
    """Generate audio using macOS `say` command."""
    voice = MACOS_VOICES.get(request.voice.lower())
    if not voice:
        available = ", ".join(MACOS_VOICES.keys())
        raise HTTPException(400, f"Unknown voice: {request.voice}. Available: {available}")

    # Calculate rate (default is ~175 wpm for say)
    rate = int(175 * request.speed)

    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = ["say", "-v", voice, "-r", str(rate), "-o", tmp_path, request.input]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise HTTPException(500, f"TTS failed: {stderr.decode()}")

        if request.response_format == "wav":
            # Convert AIFF to WAV using ffmpeg
            wav_path = tmp_path.replace(".aiff", ".wav")
            conv = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", tmp_path, "-ar", "22050", "-ac", "1", wav_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await conv.communicate()
            with open(wav_path, "rb") as f:
                data = f.read()
            os.unlink(wav_path)
        else:
            with open(tmp_path, "rb") as f:
                data = f.read()

        return data
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# --- Model listing for admin ---

def get_audio_models() -> dict:
    """Return available audio models for admin display."""
    return {
        "stt": [
            {"name": m, "provider": "whisper-local", "type": "audio"}
            for m in WHISPER_MODELS.keys()
        ],
        "tts": [
            {"name": "tts-local", "provider": "macos-say", "type": "tts",
             "voices": list(MACOS_VOICES.keys())},
        ],
    }
