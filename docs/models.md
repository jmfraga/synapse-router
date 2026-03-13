# Synapse Router — Catálogo de Modelos

> Generado: 2026-03-13 | Total: **391 modelos** en **7 providers**

## Ollama (Local) — 7 modelos

Ejecución local en Mac Mini M4 (64 GB RAM, GPU Metal). Sin costo, privacidad total.

| Modelo | Tipo | Notas |
|--------|------|-------|
| `deepseek-r1:32b` | language | Razonamiento avanzado. Necesita max_tokens alto (fase "thinking") |
| `glm-4.7-flash:latest` | language | ChatGLM rápido. Bug conocido: puede devolver contenido vacío |
| `glm4:9b-chat-fp16` | language | ChatGLM 9B en FP16 |
| `gpt-oss:20b` | language | GPT-OSS 20B |
| `llama3.1:8b` | language | Clasificador de Smart Routes. Rápido y confiable |
| `llama3.2-vision:11b` | language | Multimodal (texto + imagen) |
| `qwen3.5:35b-a3b` | language | Qwen MoE. Bug conocido: puede devolver contenido vacío |

---

## Groq — 18 modelos

Ultra-rápido (inferencia en hardware especializado). Tier gratuito con rate limits.

### Language (16)
| Modelo | Notas |
|--------|-------|
| `allam-2-7b` | Modelo árabe |
| `groq/compound` | Modelo compuesto Groq |
| `groq/compound-mini` | Versión mini |
| `llama-3.1-8b-instant` | Llama 8B, muy rápido |
| `llama-3.3-70b-versatile` | Llama 70B, excelente balance velocidad/calidad |
| `meta-llama/llama-4-scout-17b-16e-instruct` | Llama 4 Scout MoE |
| `meta-llama/llama-prompt-guard-2-22m` | Safety guard |
| `meta-llama/llama-prompt-guard-2-86m` | Safety guard (mayor) |
| `moonshotai/kimi-k2-instruct` | Kimi K2 |
| `moonshotai/kimi-k2-instruct-0905` | Kimi K2 (sept 2025) |
| `openai/gpt-oss-120b` | GPT-OSS 120B en Groq |
| `openai/gpt-oss-20b` | GPT-OSS 20B en Groq |
| `openai/gpt-oss-safeguard-20b` | GPT-OSS con safety |
| `qwen/qwen3-32b` | Qwen 32B |
| `canopylabs/orpheus-arabic-saudi` | Voz árabe saudí |
| `canopylabs/orpheus-v1-english` | Voz inglés |

### Audio (2)
| Modelo | Notas |
|--------|-------|
| `whisper-large-v3` | Transcripción (STT) |
| `whisper-large-v3-turbo` | Transcripción rápida |

---

## NVIDIA NIM — 186 modelos

Catálogo más extenso. Incluye modelos de investigación y especializados.

### Language (173)
| Modelo | Notas |
|--------|-------|
| `deepseek-ai/deepseek-v3.1` | DeepSeek V3.1 |
| `deepseek-ai/deepseek-v3.2` | DeepSeek V3.2 |
| `deepseek-ai/deepseek-r1-distill-qwen-32b` | DeepSeek R1 destilado |
| `meta/llama-3.1-405b-instruct` | Llama 405B (el más grande) |
| `meta/llama-3.3-70b-instruct` | Llama 3.3 70B |
| `meta/llama-4-maverick-17b-128e-instruct` | Llama 4 Maverick MoE |
| `meta/llama-4-scout-17b-16e-instruct` | Llama 4 Scout MoE |
| `mistralai/mistral-large-3-675b-instruct-2512` | Mistral Large 675B |
| `mistralai/devstral-2-123b-instruct-2512` | Devstral (coding) |
| `mistralai/mistral-nemotron` | Mistral-Nemotron |
| `google/gemma-3-27b-it` | Gemma 3 27B |
| `qwen/qwen3-coder-480b-a35b-instruct` | Qwen 3 Coder 480B MoE |
| `qwen/qwen3.5-397b-a17b` | Qwen 3.5 397B MoE |
| `moonshotai/kimi-k2.5` | Kimi K2.5 |
| `z-ai/glm5` | GLM5 |
| `minimaxai/minimax-m2.5` | MiniMax M2.5 |
| `nvidia/llama-3.1-nemotron-ultra-253b-v1` | Nemotron Ultra 253B |
| `nvidia/llama-3.3-nemotron-super-49b-v1.5` | Nemotron Super 49B |
| `writer/palmyra-med-70b` | Especializado en medicina |
| `writer/palmyra-fin-70b-32k` | Especializado en finanzas |
| ... | **+153 modelos más** (ver API: `/admin/api/models`) |

### Embedding (13)
| Modelo | Notas |
|--------|-------|
| `nvidia/nv-embedqa-e5-v5` | Embeddings de propósito general |
| `nvidia/nv-embedcode-7b-v1` | Embeddings de código |
| `nvidia/llama-nemotron-embed-1b-v2` | Embeddings ligero |
| `baai/bge-m3` | BGE-M3 multilingüe |
| `snowflake/arctic-embed-l` | Arctic embeddings |
| ... | +8 más |

---

## Anthropic — 9 modelos

Claude — los mejores modelos de razonamiento y seguimiento de instrucciones.

| Modelo | Notas |
|--------|-------|
| `claude-opus-4-6` | **El más capaz** (1M contexto). Razonamiento, análisis profundo |
| `claude-opus-4-5-20251101` | Opus 4.5 |
| `claude-opus-4-1-20250805` | Opus 4.1 |
| `claude-opus-4-20250514` | Opus 4.0 |
| `claude-sonnet-4-6` | Balance velocidad/calidad. Bueno para coding |
| `claude-sonnet-4-5-20250929` | Sonnet 4.5 |
| `claude-sonnet-4-20250514` | Sonnet 4.0 |
| `claude-haiku-4-5-20251001` | El más rápido y económico |
| `claude-3-haiku-20240307` | Haiku legacy |

---

## OpenAI — 121 modelos

GPT, o-series (razonamiento), DALL-E, TTS, Whisper.

### Language (109)
| Modelo | Notas |
|--------|-------|
| `gpt-5.4` | **Último modelo GPT** (marzo 2026) |
| `gpt-5.4-pro` | Versión pro con más capacidad |
| `gpt-5.2` | GPT-5.2 |
| `gpt-5.1` | GPT-5.1 |
| `gpt-5` | GPT-5 |
| `gpt-4o` | GPT-4o (multimodal) |
| `gpt-4.1` | GPT-4.1 |
| `gpt-4.1-mini` | Mini (rápido/económico) |
| `gpt-4.1-nano` | Nano (el más ligero) |
| `o4-mini` | Razonamiento económico |
| `o3` | Razonamiento avanzado |
| `o3-mini` | Razonamiento compacto |
| `o1` | Razonamiento original |
| `o1-pro` | Razonamiento pro |
| `gpt-5-codex` | Especializado en código |
| `gpt-5.1-codex` | Codex 5.1 |
| `gpt-5.2-codex` | Codex 5.2 |
| ... | +92 variantes, audio, realtime, search |

### Otros
| Modelo | Tipo | Notas |
|--------|------|-------|
| `dall-e-3` | image | Generación de imágenes |
| `dall-e-2` | image | Generación de imágenes (legacy) |
| `tts-1-hd` | tts | Texto a voz (alta calidad) |
| `tts-1` | tts | Texto a voz (estándar) |
| `whisper-1` | audio | Transcripción cloud |
| `text-embedding-3-large` | embedding | Embeddings (mejor calidad) |
| `text-embedding-3-small` | embedding | Embeddings (económico) |
| `omni-moderation-latest` | moderation | Moderación de contenido |

---

## Google Gemini — 45 modelos

Gemini, Gemma (open source), Imagen, Veo (video).

### Language (40)
| Modelo | Notas |
|--------|-------|
| `gemini-3.1-pro-preview` | **Último Gemini Pro** |
| `gemini-3-pro-preview` | Gemini 3 Pro |
| `gemini-2.5-pro` | Gemini 2.5 Pro |
| `gemini-2.5-flash` | Flash (rápido/económico) |
| `gemini-2.5-flash-lite` | Lite (el más económico) |
| `gemini-2.0-flash` | Flash 2.0 |
| `gemini-3-flash-preview` | Flash 3.0 |
| `deep-research-pro-preview-12-2025` | Investigación profunda |
| `gemma-3-27b-it` | Gemma 3 27B (open source) |
| `gemma-3n-e4b-it` | Gemma 3N eficiente |
| ... | +30 variantes |

### Otros
| Modelo | Tipo | Notas |
|--------|------|-------|
| `imagen-4.0-ultra-generate-001` | image | Generación de imágenes (ultra) |
| `imagen-4.0-generate-001` | image | Generación de imágenes |
| `gemini-embedding-001` | embedding | Embeddings |
| `veo-3.1-generate-preview` | language* | Generación de video |

---

## Perplexity — 5 modelos

Modelos con búsqueda web integrada. Respuestas con fuentes citadas.

| Modelo | Notas |
|--------|-------|
| `sonar-pro` | El más capaz, respuestas detalladas con fuentes |
| `sonar` | Balance velocidad/calidad |
| `sonar-reasoning-pro` | Razonamiento con búsqueda web |
| `sonar-reasoning` | Razonamiento (estándar) |
| `sonar-deep-research` | Investigación profunda multi-paso |

---

## Resumen por tipo

| Tipo | Cantidad | Uso |
|------|----------|-----|
| Language (LLM) | 359 | Chat, razonamiento, código, análisis |
| Embedding | 18 | Vectorización de texto para búsqueda |
| Image | 5 | Generación de imágenes |
| TTS | 4 | Texto a voz |
| Audio/STT | 3 | Transcripción de voz |
| Moderation | 2 | Filtrado de contenido |

## Modelos recomendados por caso de uso

| Caso de uso | Modelo recomendado | Provider | Por qué |
|-------------|-------------------|----------|---------|
| **General / Smart Route** | `auto` | Synapse | Clasificador elige automáticamente |
| **Razonamiento complejo** | `claude-opus-4-6` | Anthropic | 1M contexto, mejor razonamiento |
| **Código** | `claude-sonnet-4-6` | Anthropic | Rápido, excelente para coding |
| **Respuesta rápida** | `llama-3.3-70b-versatile` | Groq | Ultra-rápido, buena calidad |
| **Medicina** | `writer/palmyra-med-70b` | NVIDIA | Entrenado en datos médicos |
| **Búsqueda web** | `sonar-pro` | Perplexity | Respuestas con fuentes citadas |
| **Privacidad total** | `deepseek-r1:32b` | Ollama | 100% local, no sale de la red |
| **Económico** | `gemini-2.5-flash-lite` | Google | Muy barato, buena calidad |
| **Imágenes** | `dall-e-3` | OpenAI | Generación de imágenes |
| **Embeddings** | `text-embedding-3-large` | OpenAI | Mejor calidad para RAG |
| **Transcripción** | `whisper-large-v3` | Local | Whisper en GPU Metal, excelente en español |
