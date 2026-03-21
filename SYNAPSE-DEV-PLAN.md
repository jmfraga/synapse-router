# Synapse Router — Development Plan

## Objetivo
Hacer que Synapse Router funcione como gateway de modelos para OpenClaw:
- `/v1/models` devuelve la lista de modelos disponibles
- `/v1/chat/completions` rutea correctamente a cualquier provider
- Tool-use/function calling pasa transparente (no se rompe)
- usage_logs registra todas las llamadas (métricas)

## Estado actual (2026-03-21)
- Servicio: corriendo en M4 (puerto 8800, ~/synapse-router/)
- LiteLLM: 1.82.5 (recién actualizado de 1.63.11)
- Python: 3.12.13
- DB: synapse.db (SQLite) — 9 providers, 12 smart routes, 3701 usage logs
- Bug 1: `/v1/models` devuelve 0 modelos
- Bug 2: Tool-use passthrough roto
- Bug 3: `__annotations__` error (TranscriptionCreateParams en Python 3.12)
- Chat completions SÍ funcionan (MiniMax, Haiku, Sonnet probados directamente)

## Sandbox
- RPi5 Prototipos: `jmfraga@100.101.100.7` (8GB RAM, 99GB disco, Debian aarch64)
- Instalar OpenClaw mínimo con 1 agente de prueba apuntando a Synapse
- Validar end-to-end: agente → Synapse → modelo → respuesta con tools

## Reglas ESTRICTAS
1. **NO SSH a 100.71.128.102** (Pi producción OpenClaw) — NUNCA
2. **NO modificar** MedExpert ni Maya
3. **NO cambiar** API keys existentes en .env o providers
4. **Modelos para pruebas**: Groq, Nvidia, MiniMax = libre. Anthropic = solo Haiku. OpenAI = solo modelos baratos. Ollama = sin restricción
5. **Reiniciar Synapse** solo con: `launchctl kickstart -k gui/$(id -u)/com.jmfraga.synapse-router`
6. **Backup antes de editar** archivos críticos

## Código relevante
```
~/synapse-router/
├── synapse/
│   ├── main.py          — FastAPI app, endpoints
│   ├── config.py         — Settings (env vars SYNAPSE_*)
│   ├── routes/           — API route handlers
│   ├── models/           — SQLAlchemy models
│   └── services/         — Business logic
├── .env                  — API keys y config
├── synapse.db            — SQLite database
├── requirements.txt
└── .venv/                — Python virtual environment
```

## Providers configurados en DB
| Provider | Base URL | Status |
|----------|----------|--------|
| ollama | http://localhost:11434 | Activo |
| groq | (via LiteLLM) | Activo |
| nvidia | https://integrate.api.nvidia.com/v1 | Activo |
| anthropic | (via LiteLLM) | Activo |
| openai | (via LiteLLM) | Activo |
| gemini | (via LiteLLM) | Activo |
| perplexity | (via LiteLLM) | Activo |
| minimax | (via LiteLLM) | Activo |

## API Keys (ya configuradas en .env)
Las keys ya están en el archivo .env — NO las modifiques, solo úsalas.

## Tasks ordenadas por prioridad

### Task 1: Fix /v1/models endpoint
- Investigar por qué devuelve lista vacía
- Los modelos están en la DB (providers table) pero no se cargan al runtime
- Puede ser que el upgrade de LiteLLM cambió el API de model listing
- Verificar: `curl http://localhost:8800/v1/models`

### Task 2: Fix tool-use passthrough
- Probar: enviar request con `tools` parameter a Synapse
- Verificar que Synapse pasa `tools` transparente al provider
- Verificar que la respuesta con `tool_calls` se devuelve intacta
- Test con MiniMax y Haiku (ambos soportan tools)
- El bug reportado era "TTS markup en vez de API tool calls"

### Task 3: Setup sandbox OpenClaw en Pi Prototipos
- SSH: `jmfraga@100.101.100.7`
- Instalar Node.js + OpenClaw mínimo
- Configurar 1 agente apuntando a Synapse en M4 (100.72.169.113:8800)
- Probar interacción completa

### Task 4: Test end-to-end con tools
- Agente sandbox usa tool (ej. exec) → Synapse → modelo → respuesta
- Verificar métricas en usage_logs

### Task 5: Documentar
- Actualizar README del repo
- Documentar config necesaria para que OpenClaw producción migre a Synapse
- `cd ~/synapse-router && git add -A && git commit -m "fix: model list + tool-use passthrough" && git push`

## Reportar resultados
Al terminar, envía reporte a Juan Ma por Telegram con:
- Qué tasks se completaron
- Qué quedó pendiente
- Si OpenClaw producción puede migrar a Synapse
