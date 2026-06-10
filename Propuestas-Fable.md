# Propuestas Fable — synapse-router
> Auditoría: 2026-06-10 · Auditor: fable-auditor (Fable-5) · Estado: pendiente de revisión
> Instrucción para la sesión que implemente: marcar [x] cada hallazgo resuelto y anotar fecha/commit. NO borrar hallazgos.

## Resumen (3-5 líneas)
Synapse v2 (litellm.Router) está sano en lo arquitectónico: auth Bearer con hash, sticky fallback MLX bien documentado, sanitización TTS/gpt-oss vigente. Los problemas graves son de higiene de secretos (keys de 8 providers en texto plano en `synapse.db` modo 644 + 3 backups con las mismas keys, `.env` 644) y de exposición (bind `*:8800` con `/v1/models`, `/health` y `/metrics` sin auth). Además hay ~138 líneas de código corriendo en producción sin commitear y un README que describe un clasificador que ya no existe en el request path. Nota clave para el solicitante: **el costo del clasificador por request hoy es cero — v2 lo eliminó por completo** (`completions.py:3`); el riesgo actual no es su costo sino que la documentación lo sigue anunciando.

## Hallazgos

### F-1. API keys de providers en texto plano en SQLite legible + backups — [ALTA]
- **Dimensión**: seguridad
- **Evidencia**: `sqlite3 synapse.db "SELECT name, ..."` → 8 providers con key `DB-STORED` (groq, nvidia, anthropic, openai, gemini, perplexity, minimax, mlx). `stat -f '%Sp' synapse.db` → `-rw-r--r--` (644). Mismas keys duplicadas en 3 backups del dir: `synapse.db.bak-202604121027`, `synapse.db.bak-phi4-final-20260504193203`, `synapse.db.bak-pre-phi4-cleanup-202605041837`. `.env` también 644 con las mismas keys (tercera copia). `synapse/models/provider.py:17` (`api_key_value` en Text plano).
- **Propuesta**: (1) `chmod 600 .env synapse.db synapse.db.bak-*`; (2) elegir UNA fuente de verdad para keys — recomiendo env (`.env` 600) y vaciar `api_key_value` en DB, porque hoy `_get_key()` (litellm_router.py:287-293) prioriza DB y la copia env puede quedar stale sin que nadie lo note; (3) borrar o mover los 3 backups (son de abril/mayo, pre-cleanup ya consumado).
- **Esfuerzo**: trivial
- **Estado**: [ ] pendiente

### F-2. Bind en todas las interfaces con endpoints sin auth — [ALTA]
- **Dimensión**: seguridad
- **Evidencia**: `lsof -iTCP:8800` → `Python 715 ... TCP *:8800 (LISTEN)`. `.env` → `SYNAPSE_HOST=0.0.0.0`. Sin auth: `/health` y `/metrics` (main.py:55-119, expone modelos/rutas/volúmenes) y **`/v1/models`** (completions.py:35-36 — no tiene `Depends(authenticate)`, a diferencia de `/v1/chat/completions`). El admin usa HTTP Basic sobre HTTP plano (admin.py:45-47), visible para toda la LAN de casa, no solo Tailscale.
- **Propuesta**: bind a la IP de Tailscale (100.72.169.113) o a 127.0.0.1 + `tailscale serve`; y agregar `Depends(authenticate)` a `/v1/models`. `/health` puede quedar abierto (es el target natural de un watchdog).
- **Esfuerzo**: trivial
- **Estado**: [ ] pendiente

### F-3. Código de producción sin commitear desde hace semanas — [ALTA]
- **Dimensión**: confiabilidad
- **Evidencia**: `git diff --stat` → 138 líneas modificadas en `synapse/services/litellm_router.py` (+120: todo el bloque SmartRoute-as-alias, líneas 171-252, incluye el sticky fallback MLX), `completions.py`, `admin.py`. Último commit `15aad89` y archivos modificados desde abril; el servicio corre con este código hoy (usage_logs al 2026-06-10 14:17). 6+ archivos útiles sin trackear (`gemma4_*.py`, `arena/`, plists).
- **Propuesta**: commitear el estado actual en 2-3 commits lógicos (smart-route aliases + sticky fallback, arena, plists). Sin esto, un `git checkout` o un clone en otra máquina pierde el fix del zombie-loop.
- **Esfuerzo**: trivial
- **Estado**: [ ] pendiente

### F-4. README describe clasificador y Smart Routes que ya no existen en el request path — [MEDIA]
- **Dimensión**: alucinación
- **Evidencia**: `README.md` (sección Features): "Smart Routes — ruteo por intención con clasificador LLM local (llama3.1:8b)". Contradice `synapse/routers/completions.py:3`: `"v2: powered by litellm.Router — no classifier, no Smart Routes"`. El clasificador no corre en ningún request (cero referencias en el path de `/v1/chat/completions`); las SmartRoutes hoy solo sobreviven como aliases estáticos de modelo (litellm_router.py:171-252), sin clasificación por intención.
- **Propuesta**: actualizar README a la arquitectura v2 (router litellm, aliases, sin clasificador). Riesgo concreto si no: una sesión futura "optimiza" o "repara" un clasificador inexistente, o reporta su costo por request (que es 0).
- **Esfuerzo**: moderado
- **Estado**: [ ] pendiente

### F-5. Excepciones internas de providers expuestas al cliente — [MEDIA]
- **Dimensión**: seguridad
- **Evidencia**: `completions.py:162` → `raise HTTPException(502, f"Provider error: {e}")`; `completions.py:194-195` → stream manda `str(e)` crudo en SSE. Las excepciones de litellm suelen incluir api_base, nombre interno de deployment y fragmentos de la respuesta del provider.
- **Propuesta**: responder mensaje genérico + request id al cliente; el detalle completo ya queda en `logger.exception` (línea 161). En el stream, agregar `logger.exception` (hoy el error ni se loggea server-side) y emitir mensaje genérico.
- **Esfuerzo**: trivial
- **Estado**: [ ] pendiente

### F-6. Dashboard /metrics muerto: route_health siempre vacío — [MEDIA]
- **Dimensión**: confiabilidad
- **Evidencia**: `litellm_callback.py:58` y `:93` escriben `smart_route_name=""` en TODO log; pero las 3 queries de `/metrics` (main.py:65-104) filtran `WHERE smart_route_name <> ''`. Verificado: `sqlite3 synapse.db` → 12 requests últimos 7 días, todos con `smart_route_name=''` → `route_health` y `route_details` devuelven `[]` siempre. El "health dashboard" del commit `15aad89` reporta verde-vacío sin importar el estado real.
- **Propuesta**: en el callback, poblar `smart_route_name` con el `model_name` del deployment cuando el request entró por un alias (está en `kwargs["litellm_params"]["metadata"]` / `model_group`), o cambiar las queries para agrupar por `model`/`provider` en vez del campo vestigial.
- **Esfuerzo**: moderado
- **Estado**: [ ] pendiente

### F-7. Errores tragados en descubrimiento de modelos y costo de fallos — [MEDIA]
- **Dimensión**: confiabilidad
- **Evidencia**: `admin.py:1194` (dentro de `_fetch_models_for_provider`) → `logger.debug(f"Could not fetch models for {name}: {e}")` + `return []`: si un provider falla, sus modelos desaparecen de `/v1/models` en silencio (nivel debug = invisible con logging INFO). `litellm_callback.py:38-41` → `completion_cost` con `except: pass`.
- **Propuesta**: subir a `logger.warning` con nombre de provider; opcionalmente exponer en `/metrics` un contador de providers que fallaron el discovery.
- **Esfuerzo**: trivial
- **Estado**: [ ] pendiente

### F-8. /v1/models sin caché: fan-out vivo a ~9 providers por request, sin auth — [BAJA]
- **Dimensión**: eficiencia
- **Evidencia**: `completions.py:49-71` llama `_fetch_models_for_provider` (HTTP real, timeout 10s c/u, admin.py:1128-1134) por cada provider en cada GET, sin TTL ni memo. Combinado con F-2 (endpoint sin auth), cualquier cliente LAN puede disparar ráfagas de requests salientes a 6 APIs cloud.
- **Propuesta**: caché in-memory con TTL 120-300s (dict módulo-level + timestamp basta; ya existe el patrón singleton en litellm_router.py:20-22).
- **Esfuerzo**: trivial
- **Estado**: [ ] pendiente

### F-9. Sin watchdog vivo-pero-colgado + aliases de agentes muertos — [BAJA]
- **Dimensión**: cross-learning
- **Evidencia**: `com.jmfraga.synapse-router.plist` solo tiene `KeepAlive` (cubre crash, no hang) — misma brecha que motivó el watchdog 2-stage de Qwen3.6 (memoria `project_qwen36_watchdog.md`: POST real, no solo proceso vivo). Y `sqlite3 synapse.db "SELECT ... FROM smart_routes"` → 15 rutas habilitadas que registran deployments para agentes apagados (OpenClaw-Core, PM-Smart, Chappie, Echo, Argus… OpenClaw RPi5 OFF 2026-06-09; la memoria `feedback_synapse_smart_routes_vestige` ya autoriza limpiarlas sin pedir confirmación).
- **Propuesta**: (1) launchd watchdog cada 5 min con GET `/health` + restart si no responde (reusar el script de Qwen3.6); (2) deshabilitar las SmartRoutes de agentes OpenClaw apagados, dejando solo `essayrubric-eval` y las que sigan vivas (Maya si aplica).
- **Esfuerzo**: moderado
- **Estado**: [ ] pendiente

## Notas positivas (verificadas, sin hallazgo)
- **Auth de API sólida**: Bearer token con SHA-256 + flag `is_active` en DB (`services/auth.py:27-35`); admin con `secrets.compare_digest` (admin.py:46-47) — no cambiar.
- **Sin secretos en git ni en logs**: `.gitignore` cubre `.env` y `*.db`; `git ls-files` confirma que no están trackeados; grep de patrones de keys (`sk-ant|nvapi-|gsk_|pplx-|AIzaSy`) en los 5.5MB de logs launchd → 0 hits.
- **Lección zombie-loop aplicada y documentada**: sticky fallback MLX (`allowed_fails=3`/`cooldown_time=600` solo para hosts locales) con comentario que cita el incidente 2026-05-04 (litellm_router.py:95-113). Ejemplar — solo falta commitearlo (F-3).
- **Config litellm conforme a la memoria**: `drop_params`, `modify_params`, `request_timeout=120` (litellm_router.py:255-258) coinciden con `project_litellm_config.md`.
- **Sanitización vigente en ambos paths**: TTS markup, gpt-oss channels y strip de `reasoning_content`/`thinking_blocks` aplicados en non-stream y stream (`sanitizers.py`, completions.py:165,190).
- **Callback de uso registra éxito Y fallo** en `usage_logs` (litellm_callback.py) — la base para métricas reales ya existe; solo el filtro está roto (F-6).

## Implementado en auditorías previas
(Primera auditoría — vacío.)
