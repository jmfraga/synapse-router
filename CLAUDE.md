# Notas para sesiones

> Gateway OpenAI-compat. Si tienes acceso al mapa interno, vive en `jmfraga/plan-infraestructura`
> (privado). Esta nota es pública a propósito: **solo reglas genéricas, sin topología interna.**

## Reglas de oro
- **No rompas el contrato OpenAI-compat** (`/v1/chat/completions`, `/v1/models`, `/v1/audio/*`):
  streaming, tool-use forward y formato de mensajes. Hay clientes que dependen de él — mantén compatibilidad.
- **NUNCA** commitear `.env`, claves de API, `*.db` ni datos. `git add <archivo>`, nunca `git add -A` ciego.
- **Soft restarts** y verifica el baseline antes de sobrescribir.
