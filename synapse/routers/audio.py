"""Audio endpoints: speech-to-text (transcription) and text-to-speech.

Compatible with OpenAI's audio API format:
- POST /v1/audio/transcriptions — STT: whisper-local (default), mlx-audio,
  groq, openai — routed by "provider/model" prefix like chat completions.
- POST /v1/audio/speech — TTS: tts-local (macOS say, default), mlx-audio, openai.

Model naming mirrors the LLM convention:
  "whisper-large-v3"              → whisper-server local :8178 (bare = local)
  "mlx-audio/<model>"             → mlx-audio :8090 (Parakeet STT / Sohee TTS)
  "groq/whisper-large-v3-turbo"   → Groq cloud STT
  "openai/gpt-4o-transcribe"      → OpenAI cloud STT
  "openai/tts-1"                  → OpenAI cloud TTS
API keys resolve from the providers table (DB value > env), same as chat.
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.config import get_settings
from synapse.database import get_db
from synapse.models import ApiKey, Provider, UsageLog
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
MLX_AUDIO_URL = os.environ.get("SYNAPSE_MLX_AUDIO_URL", "http://localhost:8090")

# Audio-capable backends addressable as "prefix/model". `key_provider` names the
# row in the providers table whose API key gets used (None = no auth, local).
# To add a backend (e.g. DGX NIM STT): add an entry here — the endpoints are
# OpenAI-compatible so the forwarding logic is shared.
STT_BACKENDS: dict[str, dict] = {
    "mlx-audio": {"base_url": f"{MLX_AUDIO_URL}/v1", "key_provider": None},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_provider": "groq"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_provider": "openai"},
}
TTS_BACKENDS: dict[str, dict] = {
    "mlx-audio": {"base_url": f"{MLX_AUDIO_URL}/v1", "key_provider": None},
    "openai": {"base_url": "https://api.openai.com/v1", "key_provider": "openai"},
}


def _split_backend(model: str) -> tuple[Optional[str], str]:
    """Split "prefix/model" → (prefix, model). Bare names return (None, model)."""
    if "/" in model:
        prefix, rest = model.split("/", 1)
        return prefix, rest
    return None, model


async def _resolve_backend_key(db: AsyncSession, provider_name: Optional[str]) -> str:
    """API key for a backend: providers table value > env var. Empty for local."""
    if not provider_name:
        return ""
    result = await db.execute(select(Provider).where(Provider.name == provider_name))
    prov = result.scalar_one_or_none()
    if prov is None:
        return ""
    if prov.api_key_value:
        return prov.api_key_value
    if prov.api_key_env:
        return os.environ.get(prov.api_key_env, "")
    return ""

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
    """Transcribe audio to text — local whisper-server or a cloud/local backend.

    Compatible with OpenAI's /v1/audio/transcriptions format.
    Models: whisper-large-v3|medium|base (local), mlx-audio/<m>, groq/<m>, openai/<m>
    """
    start = time.monotonic()

    # Read uploaded file
    audio_data = await file.read()
    if not audio_data:
        raise HTTPException(400, "Empty audio file")

    lang = language or "es"

    # Prefixed model → OpenAI-compatible backend (mlx-audio, groq, openai)
    prefix, backend_model = _split_backend(model)
    if prefix is not None:
        backend = STT_BACKENDS.get(prefix)
        if backend is None:
            raise HTTPException(400, f"Unknown STT backend '{prefix}'. Available: {sorted(STT_BACKENDS)}")
        key = await _resolve_backend_key(db, backend["key_provider"])
        if backend["key_provider"] and not key:
            raise HTTPException(400, f"No API key configured for provider '{backend['key_provider']}'")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        data = {"model": backend_model, "response_format": response_format or "json"}
        if language:
            data["language"] = language
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{backend['base_url']}/audio/transcriptions",
                    headers=headers,
                    files={"file": (file.filename or "audio.wav", audio_data, file.content_type or "audio/wav")},
                    data=data,
                )
        except httpx.HTTPError as e:
            raise HTTPException(503, f"STT backend '{prefix}' unavailable: {e}")
        if resp.status_code != 200:
            raise HTTPException(502, f"STT backend '{prefix}' error {resp.status_code}: {resp.text[:200]}")
        try:
            result = resp.json()
        except Exception:
            result = {"text": resp.text.strip()}

        elapsed_ms = int((time.monotonic() - start) * 1000)
        db.add(UsageLog(
            api_key_id=api_key.id,
            provider=f"stt-{prefix}",
            model=model,
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            latency_ms=elapsed_ms, cost_usd=0.0, status="success",
            route_path=f"stt-{prefix}/{backend_model}",
        ))
        await db.commit()
        return result

    # Bare model → local whisper-server (default path, unchanged)
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

        # Validate response is valid JSON before parsing
        resp_text = resp.text.strip()
        if not resp_text:
            raise HTTPException(502, "Whisper server returned empty response")
        try:
            result = resp.json()
        except Exception:
            logger.error(f"Whisper server returned invalid JSON: {resp_text[:200]}")
            raise HTTPException(502, f"Whisper server returned invalid response")

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
    """Generate speech from text — macOS `say` (default) or an OpenAI-compatible backend.

    Compatible with OpenAI's /v1/audio/speech format.
    Models: tts-local (macOS say), mlx-audio/<model>, openai/tts-1, openai/gpt-4o-mini-tts
    Voices tts-local: paulina, monica, jorge, juan, allison, samantha, tom
    """
    start = time.monotonic()

    prefix, backend_model = _split_backend(request.model)
    if request.model == "tts-local" or prefix is None:
        if request.model != "tts-local":
            raise HTTPException(
                400,
                f"Unknown TTS model: {request.model}. Available: tts-local, "
                f"{', '.join(f'{p}/<model>' for p in sorted(TTS_BACKENDS))}",
            )
        audio_data = await _tts_macos_say(request)
        provider_label = "tts-local"
        route_path = f"tts-local/{request.voice}"
        content_type = "audio/wav" if request.response_format == "wav" else "audio/aiff"
    else:
        backend = TTS_BACKENDS.get(prefix)
        if backend is None:
            raise HTTPException(400, f"Unknown TTS backend '{prefix}'. Available: {sorted(TTS_BACKENDS)}")
        key = await _resolve_backend_key(db, backend["key_provider"])
        if backend["key_provider"] and not key:
            raise HTTPException(400, f"No API key configured for provider '{backend['key_provider']}'")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        payload = {
            "model": backend_model,
            "input": request.input,
            "voice": request.voice,
            "response_format": request.response_format,
            "speed": request.speed,
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{backend['base_url']}/audio/speech",
                    headers=headers, json=payload,
                )
        except httpx.HTTPError as e:
            raise HTTPException(503, f"TTS backend '{prefix}' unavailable: {e}")
        if resp.status_code != 200:
            raise HTTPException(502, f"TTS backend '{prefix}' error {resp.status_code}: {resp.text[:200]}")
        audio_data = resp.content
        provider_label = f"tts-{prefix}"
        route_path = f"tts-{prefix}/{backend_model}"
        content_type = resp.headers.get("content-type", "audio/mpeg")

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # Log usage
    log = UsageLog(
        api_key_id=api_key.id,
        provider=provider_label,
        model=request.model,
        prompt_tokens=len(request.input.split()),
        completion_tokens=0,
        total_tokens=len(request.input.split()),
        latency_ms=elapsed_ms,
        cost_usd=0.0,
        status="success",
        route_path=route_path,
    )
    db.add(log)
    await db.commit()

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
    """Return available audio models for admin display.

    Cloud entries only appear when the provider's API key is present in env;
    keys stored only in DB won't show here (display-only, dispatch still works).
    """
    stt = [
        {"name": m, "provider": "whisper-local", "type": "audio"}
        for m in WHISPER_MODELS.keys()
    ]
    stt.append({"name": "mlx-audio/mlx-community/whisper-large-v3-turbo", "provider": "mlx-audio", "type": "audio"})
    tts = [
        {"name": "tts-local", "provider": "macos-say", "type": "tts",
         "voices": list(MACOS_VOICES.keys())},
        {"name": "mlx-audio/mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
         "provider": "mlx-audio", "type": "tts"},
    ]
    if os.environ.get("SYNAPSE_GROQ_API_KEY"):
        stt.append({"name": "groq/whisper-large-v3-turbo", "provider": "groq", "type": "audio"})
    if os.environ.get("SYNAPSE_OPENAI_API_KEY"):
        stt.append({"name": "openai/gpt-4o-transcribe", "provider": "openai", "type": "audio"})
        stt.append({"name": "openai/whisper-1", "provider": "openai", "type": "audio"})
        tts.append({"name": "openai/gpt-4o-mini-tts", "provider": "openai", "type": "tts"})
        tts.append({"name": "openai/tts-1", "provider": "openai", "type": "tts"})
    return {"stt": stt, "tts": tts}
