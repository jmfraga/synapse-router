# Synapse Router — Manual de Administración

Guía completa para configurar y administrar Synapse Router.

---

## Tabla de Contenidos

1. [Acceso al Panel](#1-acceso-al-panel)
2. [Providers](#2-providers)
3. [Rutas Explícitas](#3-rutas-explícitas)
4. [Smart Routes](#4-smart-routes)
5. [Sistema de Fallback](#5-sistema-de-fallback)
6. [API Keys](#6-api-keys)
7. [Audio (STT / TTS)](#7-audio-stt--tts)
8. [Arena](#8-arena)
9. [Analytics](#9-analytics)
10. [QA Module](#10-qa-module)
11. [Clasificación de Modelos](#11-clasificación-de-modelos)

---

## 1. Acceso al Panel

El panel de administración está en:

```
http://<host>:8800/admin/
```

### Credenciales

Se configuran con variables de entorno:

| Variable | Default | Descripción |
|----------|---------|-------------|
| `SYNAPSE_ADMIN_USER` | `admin` | Usuario del panel |
| `SYNAPSE_ADMIN_PASSWORD` | `changeme` | Contraseña del panel |

Usa **HTTP Basic Auth**. Al acceder por primera vez el navegador pedirá usuario y contraseña.

---

## 2. Providers

Los providers son las fuentes de modelos LLM. Synapse soporta 7 providers:

| Provider | Tipo | Notas |
|----------|------|-------|
| Ollama | Local | GPU Metal, sin costo, privacidad total |
| Groq | Cloud | Ultra-rápido, gratis con límites |
| NVIDIA NIM | Cloud | Catálogo más amplio (186+ modelos) |
| Anthropic | Cloud | Claude (mejor razonamiento) |
| OpenAI | Cloud | GPT, o-series, DALL-E |
| Google Gemini | Cloud | Gemini, Gemma, Imagen |
| Perplexity | Cloud | Búsqueda web integrada |

### Crear un Provider

Desde el panel: **Providers → Agregar Provider**

| Campo | Descripción |
|-------|-------------|
| `name` | Identificador único (ej: `ollama`, `anthropic`) |
| `display_name` | Nombre visible en el panel |
| `base_url` | URL del API (ej: `http://localhost:11434` para Ollama) |
| `is_local` | Marcar si es local (afecta métricas de costo) |
| `priority` | Número entero — **menor = mayor prioridad** en cadenas de fallback |

### API Keys de Providers

Cada provider cloud necesita una API key. Se pueden configurar de 3 formas (en orden de prioridad):

1. **Desde el panel** — se guarda en la DB (mayor prioridad)
2. **Variable de entorno** — ej: `SYNAPSE_ANTHROPIC_API_KEY`
3. **Settings** — archivo de configuración

El panel muestra:
- **Origen de la key**: `db` o `env`
- **Preview**: primeros 8 caracteres
- **Expiración**: días restantes con alertas a 14 días

### Descubrimiento de Modelos

**Providers → Descubrir Modelos** consulta automáticamente la API del provider y lista todos los modelos disponibles.

- Selecciona los modelos que quieres activar (whitelist)
- Lista vacía = todos los modelos habilitados
- También puedes agregar **modelos custom** manualmente para modelos no listados en la API

### Test de Conexión

**Providers → Test** envía un mensaje de prueba al modelo seleccionado y muestra:
- Respuesta del modelo
- Latencia (ms)
- Tokens consumidos

### Prioridad

La prioridad determina el orden en cadenas de fallback dinámicas:

```
1. Ollama (local, gratis)      ← prioridad más alta
2. Groq (rápido, gratis)
3. NVIDIA NIM
4. Anthropic / OpenAI / Gemini
5. Perplexity                  ← prioridad más baja
```

---

## 3. Rutas Explícitas

Las rutas explícitas mapean patrones de nombre de modelo a providers específicos. Synapse **preserva el modelo original** del request — la ruta solo determina a qué provider enviarlo.

### Crear una Ruta

| Campo | Descripción |
|-------|-------------|
| `name` | Nombre descriptivo (ej: "Perplexity Direct") |
| `model_pattern` | Patrón de matching (ver abajo) |
| `provider_chain` | Lista ordenada de `{provider}` — el modelo del request se preserva |
| `priority` | Orden de evaluación (menor = se evalúa primero) |
| `is_enabled` | Activar/desactivar sin borrar |

### Patrones Soportados

| Patrón | Ejemplo | Matchea |
|--------|---------|---------|
| Exacto | `gpt-4o` | Solo ese modelo |
| Wildcard | `sonar*` | `sonar-pro`, `sonar-deep-research`, etc. |
| Global | `*` | Cualquier modelo |

### Cómo Funciona

La ruta define **a qué provider ir**, pero el modelo que pidió el cliente se respeta. Ejemplo:

```
Ruta: sonar* → provider: perplexity

Request: model="sonar-deep-research"
→ Matchea sonar* → envía a perplexity/sonar-deep-research

Request: model="sonar-pro"
→ Matchea sonar* → envía a perplexity/sonar-pro
```

Esto evita que Synapse intente el modelo en todos los providers (cadena dinámica), enviándolo directo al provider correcto.

### Cuándo Usar Rutas Explícitas

- **Modelos exclusivos de un provider** — ej: `sonar*` solo existe en Perplexity
- **Forzar un provider específico** — ej: siempre usar Groq para ciertos modelos
- **Evitar la cadena dinámica** — reduce errores innecesarios y latencia

Para fallbacks con modelos de diferentes providers, usa **Smart Routes** con su cadena de intenciones y default chain.

### Orden de Evaluación

Las rutas se evalúan por prioridad (menor primero). La **primera ruta que matchee** el modelo solicitado se usa. Si ninguna matchea, Synapse construye una cadena dinámica basada en la prioridad de providers.

---

## 4. Smart Routes

Las Smart Routes son el corazón del ruteo inteligente. Clasifican automáticamente la intención del mensaje y dirigen al modelo óptimo.

### Crear una Smart Route

| Campo | Descripción |
|-------|-------------|
| `name` | Identificador único (ej: `openclaw-smart`) |
| `trigger_model` | Alias que activa esta ruta (ej: `auto`) |
| `classifier_model` | Modelo que clasifica (ej: `llama3.1:8b`) |
| `classifier_prompt` | Prompt custom (opcional — se auto-genera si está vacío) |
| `intents` | Lista de intenciones con sus cadenas |
| `default_chain` | Cadena por defecto (fallback general) |

### Intenciones

Cada intención define:

```json
{
  "name": "medicina",
  "description": "Consultas médicas, farmacología, diagnóstico",
  "provider_chain": [
    {"provider": "anthropic", "model": "claude-opus-4-6"},
    {"provider": "openai", "model": "gpt-4o"}
  ]
}
```

- **name**: nombre de la categoría (lo que el clasificador devuelve)
- **description**: contexto para el clasificador — qué tipo de mensajes caen aquí
- **provider_chain**: modelos a usar, en orden (primero = principal, resto = fallback)

### Cómo Funciona el Clasificador

1. Extrae el último mensaje del usuario
2. Construye un prompt con las categorías definidas:
   ```
   Clasifica el siguiente mensaje en exactamente una categoría.
   Responde SOLO con el nombre de la categoría.

   Categorías:
   - medicina: Consultas médicas, farmacología, diagnóstico
   - coding: Programación, debugging, revisión de código
   - ...

   Mensaje: {mensaje del usuario}

   Categoría:
   ```
3. El clasificador responde con una sola palabra (ej: `medicina`)
4. Synapse busca la intención y usa su cadena de providers

**Parámetros del clasificador**: `temperature=0.0`, `max_tokens=20` — respuesta determinística y corta.

### Prompt Custom

Si el prompt auto-generado no da buenos resultados, puedes escribir uno custom. Usa `{message}` como placeholder para el mensaje del usuario.

### Default Chain

La cadena por defecto se usa cuando:

1. No hay mensaje de usuario para clasificar
2. El clasificador devuelve una intención no definida
3. La clasificación falla (error del modelo)
4. **Toda la cadena de una intención falla** (cross-layer fallback)

**Recomendación**: Configura el default chain con al menos 2 modelos de providers diferentes para máxima resiliencia.

### Flujo Completo de Resolución

```
Request llega
    │
    ├─ ¿API key tiene Smart Route asignada? → Usar esa
    ├─ ¿Modelo = trigger_model de alguna Smart Route? → Usar esa
    ├─ ¿Matchea alguna ruta explícita? → Usar esa
    └─ Ninguna → Cadena dinámica por prioridad de providers
```

---

## 5. Sistema de Fallback

Synapse tiene un sistema de fallback en múltiples niveles para maximizar la disponibilidad.

### Nivel 1 — Fallback dentro de la intención

Cada intención tiene una cadena de providers. Si el primero falla, intenta el siguiente:

```
medicina: anthropic/claude-opus → openai/gpt-4o
           ❌ falla                ✅ responde
```

Se registra como `status: "fallback"` en analytics.

### Nivel 2 — Cross-layer fallback (intención → default)

Si **todos** los modelos de una intención fallan, Synapse intenta con la cadena default como último recurso:

```
medicina: anthropic/claude-opus → openai/gpt-4o
           ❌ falla                ❌ falla
                                        │
                         ┌───────────────┘
                         ▼
          default: ollama/llama3 → groq/gemma2
                    ✅ responde
```

Se registra con `route_path: "medicina(failed) -> default/ollama/llama3"`.

### Nivel 3 — Error total

Si el default chain también falla, se devuelve error al cliente.

### Recomendaciones para Cadenas Resilientes

- **Mínimo 2 modelos** por intención, de providers diferentes
- **Mezclar local + cloud**: Ollama como fallback no depende de internet
- **Default chain robusto**: es la última línea de defensa — usa providers confiables
- **Monitorear en Analytics**: la sección "Fallback Paths" muestra qué cadenas se activan

---

## 6. API Keys

Las API keys controlan el acceso de servicios externos a Synapse.

### Crear una Key

| Campo | Descripción |
|-------|-------------|
| `name` | Nombre descriptivo (ej: "OpenClaw Production") |
| `service` | Nombre del servicio (ej: "openclaw", "medexpert") |
| `allowed_models` | `*` = todos, o lista separada por comas |
| `rate_limit_rpm` | Requests por minuto (default: 60) |
| `smart_route_id` | Smart Route asignada (opcional) |

### Formato de Key

```
syn-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

- Prefijo `syn-` + 32 caracteres aleatorios
- Se muestra **una sola vez** al crear — luego solo se ve el prefijo
- Se almacena como hash SHA256 (no se puede recuperar)

### Smart Route por Key

Cada API key puede tener una Smart Route diferente asignada. Esto permite perfiles distintos:

| Key | Servicio | Smart Route |
|-----|----------|-------------|
| syn-abc... | OpenClaw | openclaw-smart (11 intenciones médicas/técnicas) |
| syn-def... | MedExpert | medexpert-smart (intenciones solo médicas) |
| syn-ghi... | Testing | (ninguna — usa rutas explícitas) |

Si la key **no tiene** Smart Route asignada, el ruteo sigue el flujo normal (trigger_model match → rutas explícitas → cadena dinámica).

### Revocar una Key

Revocar una key la desactiva (soft delete). No se borra de la DB para mantener el historial de analytics.

---

## 7. Audio (STT / TTS)

### Speech-to-Text (Whisper Local)

Synapse incluye un servidor Whisper local corriendo en GPU Metal (Apple Silicon).

| Modelo | Archivo | Calidad | Velocidad |
|--------|---------|---------|-----------|
| `whisper-large-v3` | ggml-large-v3.bin | Excelente | Más lento |
| `whisper-medium` | ggml-medium.bin | Buena | Medio |
| `whisper-base` | ggml-base.bin | Básica | Más rápido |

**Default**: `whisper-large-v3` (mejor calidad en español).

El servidor Whisper corre en el puerto `8178` como servicio launchd independiente.

### Text-to-Speech (macOS Say)

| Voz | Idioma | Género |
|-----|--------|--------|
| `paulina` | es-MX | Femenina (default) |
| `monica` | es-ES | Femenina |
| `jorge` | es-ES | Masculino |
| `juan` | es-MX | Masculino |
| `allison` | en-US | Femenina |
| `samantha` | en-US | Femenina |
| `tom` | en-US | Masculino |

**Velocidad**: configurable de 0.5x a 2.0x (base: 175 palabras/min).

Ambos servicios son locales y sin costo ($0.00 por request).

---

## 8. Arena

El Arena permite comparar modelos side-by-side para evaluar cuál es mejor en cada categoría.

Cada modelo se envía **directo a su provider** (formato `provider:model`), sin pasar por la cadena de routing. Esto garantiza que cada modelo se ejecute exactamente donde debe, sin fallbacks ni cadena dinámica.

Las respuestas se obtienen en modo **non-streaming** (respuesta completa), lo que garantiza compatibilidad con todos los modelos incluyendo los que usan razonamiento interno (thinking models).

### Flujo de Uso

1. **Crear batalla** — elige un prompt (preset o custom) y categoría
2. **Ejecutar** — envía el prompt a 2+ modelos (locales secuencial, cloud en paralelo)
3. **Comparar** — ve las respuestas completas, métricas de velocidad y costo
4. **Calificar** — rating 1-5 por cada respuesta
5. **Scorecard** — ranking acumulado por modelo y categoría

### Categorías de Presets

| Categoría | Presets | Ejemplos |
|-----------|---------|----------|
| simple | 6 | Traducción, sentimiento, resumen |
| medicine | 2 | STEMI, diabetes farmacología |
| coding | 2 | WebSocket, Rust LRU cache |
| tool_use | 2 | Multi-step, data pipeline |
| reasoning | 2 | River puzzle, missing dollar |
| spanish | 8 | Clínica rural, urgencias neuro, contratos |

### Métricas por Resultado

| Métrica | Descripción |
|---------|-------------|
| TTFT | Time-to-first-token (ms) |
| Tokens/s | Velocidad de generación |
| Tokens totales | Cantidad de tokens generados |
| Tiempo total | Duración completa (ms) |
| Costo | Costo estimado en USD |

### Scorecard

Ranking global de modelos basado en ratings acumulados. Muestra:
- Rating promedio por modelo y categoría
- Tokens/s promedio
- TTFT promedio
- Gradiente de color (verde = mejor, rojo = peor)

### Recomendaciones

El Arena puede recomendar cambios a una Smart Route basándose en los ratings:

1. Mapea cada intención a una categoría del Arena
2. Encuentra el modelo mejor calificado en esa categoría
3. Compara con el modelo actualmente asignado
4. Muestra el delta de mejora

**Apply**: actualiza la Smart Route con el modelo recomendado en un click.

#### Mapeo Intención → Categoría

| Intención | Categoría Arena |
|-----------|----------------|
| medicina, medical, medicine | medicine |
| coding, programación, code | coding |
| tool_use, herramientas, tools | tool_use |
| reasoning, razonamiento | reasoning |
| simple, general, conversación | simple |
| spanish, español | spanish |

---

## 9. Analytics

Dashboard completo de uso, costos y rendimiento.

### Filtros de Tiempo

| Filtro | Descripción |
|--------|-------------|
| Hoy | Solo hoy |
| 7d | Últimos 7 días (default) |
| 30d | Últimos 30 días |
| Todo | Sin filtro de fecha |

### Métricas Disponibles

#### Resumen General
- Total de requests
- Costo total (USD)
- Tokens totales
- Latencia promedio (ms)
- Errores
- Fallbacks

#### Por Provider
- Requests, tokens, costo
- Latencia promedio
- Tasa de error (%)
- Tasa de fallback (%)

#### Por Modelo (Top 20)
- Requests, tokens, costo
- Latencia promedio
- Provider de origen

#### Por Servicio
- Requests, tokens, costo por API key/servicio

#### Por Intención (Smart Routes)
- Requests, costo, latencia por intención clasificada
- Errores y fallbacks por intención

#### Costo vs Calidad
Cruza datos del Arena (ratings) con uso real:
- Costo promedio por request
- Rating promedio
- Score/dólar — qué tan buena es la calidad relativa al costo

#### Latencia por Provider
Gráfico de tendencia diaria con líneas por provider (Chart.js).

#### Fallback Paths
Top 20 cadenas de fallback más usadas. Ejemplo:
```
ollama/llama3 -> groq/gemma2    (15 veces)
anthropic/claude-opus -> openai/gpt-4o    (3 veces)
medicina(failed) -> default/ollama/llama3    (1 vez)
```

#### Timeline
Gráfico de requests y costos por día.

---

## 10. QA Module

Sistema de testing integrado para validar el pipeline completo.

### Formato de Tests

Los tests se escriben en Markdown con YAML frontmatter:

```markdown
---
id: test_med_001
route: openclaw-smart
expected_intent: medicina
category: medicine
language: es
---

¿Cuál es el manejo inicial de un paciente con STEMI anterior?
```

### Modos de Ejecución

#### Classifier QA
Evalúa solo la precisión del clasificador de intenciones.

```bash
python -m synapse.qa classify --route openclaw-smart -v
```

Resultado: accuracy %, confusion matrix, misclassifications.

#### Pipeline QA
Test end-to-end: clasificación + llamada al API + evaluación de respuesta.

```bash
python -m synapse.qa pipeline --key syn-xxx --judge ollama/llama3.1:8b
```

El LLM Judge califica la respuesta 1-5 en relevancia y precisión.

#### Smoke Test
Test rápido post-cambio: 3 tests por intención, threshold 80%.

```bash
python -m synapse.qa smoke --route openclaw-smart
```

Sin `--key`: solo valida clasificación. Con `--key`: pipeline completo.

#### Historial
Detecta regresiones comparando runs anteriores.

```bash
python -m synapse.qa history
```

### Parámetros Comunes

| Flag | Descripción |
|------|-------------|
| `--route` | Filtrar por Smart Route |
| `--category` | Filtrar por categoría de test |
| `--verbose` / `-v` | Detalle por test |
| `--json` | Output en JSON |
| `--threshold` | Accuracy mínima para pasar (default: 80%) |
| `--judge` | Modelo evaluador (ej: `ollama/llama3.1:8b`) |
| `--key` | API key de Synapse para tests de pipeline |
| `--url` | URL base de Synapse (default: `http://localhost:8800`) |

---

## 11. Clasificación de Modelos

Synapse clasifica automáticamente cada modelo por tipo para filtrar en selectores y rutas.

| Tipo | Ejemplos | Uso |
|------|----------|-----|
| `language` | llama3, gpt-4o, claude | Chat completions (default) |
| `embedding` | text-embedding-3, bge-*, nomic-embed | Vectorización |
| `image` | dall-e-3, stable-diffusion, flux | Generación de imágenes |
| `tts` | tts-*, elevenlabs | Texto a voz |
| `audio` | whisper-* | Transcripción |
| `moderation` | text-moderation, omni-moderation | Moderación de contenido |
| `rerank` | rerank-* | Re-ranking de resultados |

Los selectores de modelo en el panel y Smart Routes **filtran automáticamente** modelos no-LLM, mostrando solo modelos tipo `language`.

API con filtro: `GET /admin/api/models?model_type=language`

---

## Referencia Rápida de Endpoints Admin

| Recurso | Método | Endpoint |
|---------|--------|----------|
| Dashboard | GET | `/admin/` |
| Providers | GET/POST | `/admin/api/providers` |
| Provider | PUT/DELETE | `/admin/api/providers/{id}` |
| Provider Key | PUT | `/admin/api/providers/{id}/key` |
| Descubrir Modelos | GET | `/admin/api/providers/{id}/discover` |
| Test Conexión | POST | `/admin/api/providers/{id}/test` |
| Rutas | GET/POST | `/admin/api/routes` |
| Ruta | PUT/DELETE | `/admin/api/routes/{id}` |
| Smart Routes | GET/POST | `/admin/api/smart-routes` |
| Smart Route | PUT/DELETE | `/admin/api/smart-routes/{id}` |
| Toggle Smart Route | PUT | `/admin/api/smart-routes/{id}/toggle` |
| API Keys | GET/POST | `/admin/api/keys` |
| Revocar Key | DELETE | `/admin/api/keys/{id}` |
| Arena Presets | GET | `/admin/api/arena/presets` |
| Arena Battles | GET/POST | `/admin/api/arena/battles` |
| Arena Rating | PUT | `/admin/api/arena/results/{id}/rate` |
| Scorecard | GET | `/admin/api/arena/scorecard` |
| Recomendaciones | GET | `/admin/api/arena/recommendations/{sr_id}` |
| Analytics | GET | `/admin/api/analytics?days=7` |
| Modelos | GET | `/admin/api/models?model_type=language` |
| Audio Models | GET | `/admin/api/audio-models` |
