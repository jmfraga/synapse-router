# Synapse Router

Router inteligente de LLMs con ruteo por capas, clasificación de modelos, endpoints de audio (STT/TTS), panel de administración y métricas.

## Arquitectura

```
[Servicios: OpenClaw, MedExpert, etc.]
            │
    API compatible OpenAI
            │
    ┌───────────────────────┐
    │    Synapse Router      │
    │  (FastAPI + SQLite)    │
    │                        │
    │  /v1/chat/completions  │  ← LLMs (387+ modelos)
    │  /v1/audio/transcriptions │  ← STT (Whisper local)
    │  /v1/audio/speech      │  ← TTS (macOS / cloud)
    │  /admin/               │  ← Panel de administración
    └───────┬────────────────┘
            │
     Ruteo Inteligente
     (explícito, dinámico o por intención)
            │
    ┌───┬───┼───┬───┬───┬───┐
    │   │   │   │   │   │   │
  Local Groq NV  Anth OAI Gem Perp
(Ollama)    vidia opic   ini lxty
```

## Features

### LLM Routing
- **API compatible con OpenAI** — drop-in replacement para `/v1/chat/completions`
- **7 providers**: Ollama (local), Groq, NVIDIA NIM, Anthropic, OpenAI, Gemini, Perplexity — **387+ modelos**
- **Ruteo por capas** con fallback automático por prioridad de provider
- **Smart Routes** — ruteo por intención con clasificador LLM local (llama3.1:8b)
- **Per-key routing** — API keys vinculadas a Smart Routes para servicios especializados
- **Rutas explícitas** — pattern matching con wildcards (`gpt-4*` → provider chain)
- **Streaming nativo** (SSE)

### Clasificación de Modelos
- **Categorización automática** de modelos por tipo: `language`, `image`, `tts`, `audio`, `embedding`, `moderation`, `rerank`
- Los selectores de rutas y playground **filtran modelos no-LLM** automáticamente
- Badges visuales de tipo en el panel de administración
- API con filtro: `GET /admin/api/models?model_type=language`

### Audio (STT + TTS)
- **Speech-to-Text**: `POST /v1/audio/transcriptions` — Whisper local (large-v3, medium, base)
  - Modelos en Metal (GPU Apple Silicon), excelente calidad en español
  - Compatible con formato OpenAI
- **Text-to-Speech**: `POST /v1/audio/speech` — macOS `say` con 7 voces
  - Español: Paulina (MX), Mónica (ES), Jorge (ES), Juan (MX)
  - English: Allison, Samantha, Tom
  - Velocidad configurable (0.5x – 2.0x)
- Sección dedicada en admin con grabación desde micrófono y reproducción

### Panel de Administración
- **Gestión de providers**: crear, eliminar, activar/desactivar, prioridad, API keys con expiración y alertas de rotación
- **Descubrimiento de modelos**: consulta automática a APIs de providers, selección de modelos activos, modelos custom manuales
- **Test de conexión** por provider y modelo
- **Gestión de rutas**: CRUD completo para rutas explícitas y Smart Routes
- **API keys por servicio**: generación, revocación, modelos permitidos, asignación de Smart Route
- **Métricas**: requests, costos, latencia, por provider
- **Playground**: probar chat completions directo desde el panel
- **Audio**: transcribir archivos o grabar desde el micrófono, generar y reproducir TTS

### Seguridad
- Autenticación por Bearer token (API keys con hash SHA256)
- Admin protegido con Basic Auth
- API keys de providers: DB value > env var > settings (triple fallback)

## Capas de providers (prioridad)

1. **Local (Ollama)** — sin costo, primera opción cuando el modelo lo permite
2. **Groq / NVIDIA NIM** — fallback rápido para modelos intermedios
3. **Anthropic / OpenAI / Gemini** — modelos robustos y tareas especializadas
4. **Perplexity** — búsquedas con contexto web

## Setup

```bash
cd synapse-router
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # configurar API keys
python -m synapse.main
```

### Variables de entorno

```env
SYNAPSE_HOST=0.0.0.0
SYNAPSE_PORT=8800
SYNAPSE_ADMIN_USER=admin
SYNAPSE_ADMIN_PASSWORD=tu-password-seguro

# Provider API keys (opcionales, se pueden configurar desde admin)
SYNAPSE_GROQ_API_KEY=
SYNAPSE_NVIDIA_API_KEY=
SYNAPSE_ANTHROPIC_API_KEY=
SYNAPSE_OPENAI_API_KEY=
SYNAPSE_GEMINI_API_KEY=
SYNAPSE_PERPLEXITY_API_KEY=
```

### Whisper Server (STT local)

```bash
brew install whisper-cpp ffmpeg
# Descargar modelo
curl -L -o ~/models/whisper/ggml-large-v3.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin"
# Iniciar servidor
whisper-server --model ~/models/whisper/ggml-large-v3.bin \
  --host 0.0.0.0 --port 8178 --language es --convert --threads 8
```

### launchd (macOS, servicio persistente)

```bash
# Copiar plists a LaunchAgents
cp com.jmfraga.synapse-router.plist ~/Library/LaunchAgents/
cp com.jmfraga.whisper-server.plist ~/Library/LaunchAgents/

# Activar
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jmfraga.synapse-router.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jmfraga.whisper-server.plist
```

## API

### Chat Completions

```bash
curl http://localhost:8800/v1/chat/completions \
  -H "Authorization: Bearer syn-tu-api-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "Hola"}]}'
```

### Transcripción (STT)

```bash
curl http://localhost:8800/v1/audio/transcriptions \
  -H "Authorization: Bearer syn-tu-api-key" \
  -F "file=@audio.wav" \
  -F "model=whisper-large-v3" \
  -F "language=es"
```

### Texto a Voz (TTS)

```bash
curl http://localhost:8800/v1/audio/speech \
  -H "Authorization: Bearer syn-tu-api-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "tts-local", "input": "Hola mundo", "voice": "paulina"}' \
  -o output.wav
```

## Stack

- **Python 3.12** + FastAPI + Uvicorn
- **litellm** — abstracción multi-provider
- **SQLAlchemy** (async) + SQLite
- **Jinja2** — templates del admin
- **whisper.cpp** — STT local (Metal/GPU)
- **macOS say** — TTS local

## Licencia

MIT
