# Synapse Router

Router inteligente de LLMs con ruteo por capas, panel de administración y métricas.

## Arquitectura

```
[Servicios: OpenClaw, MedExpert, etc.]
            │
        API compatible OpenAI
            │
    ┌───────────────────┐
    │   Synapse Router   │
    │  (FastAPI + SQLite) │
    └───────┬───────────┘
            │
     Ruteo Inteligente
            │
    ┌───┬───┼───┬───┬───┐
    │   │   │   │   │   │
  Local Groq NV  Anth OAI Gem
 (Ollama)    vidia opic   ini
```

## Capas de providers (prioridad)

1. **Local (Ollama)** — sin costo, primera opción cuando el modelo lo permite
2. **Groq / Nvidia** — fallback rápido para modelos intermedios
3. **Anthropic / OpenAI / Gemini** — modelos robustos y tareas especializadas
4. **Perplexity** — búsquedas con contexto web

## Features

- API compatible con OpenAI (drop-in replacement)
- Ruteo inteligente por capas con fallback automático
- Panel de administración web
- Gestión de API keys por servicio
- Métricas de uso, costos y latencia
- Cache de respuestas
- Streaming nativo

## Setup

```bash
cd synapse-router
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # configurar API keys
python -m synapse.main
```

## Licencia

MIT
