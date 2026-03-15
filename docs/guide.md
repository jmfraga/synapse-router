# Synapse Router — Guía de Integración

## ¿Qué es Synapse?

Synapse Router es un gateway inteligente de LLMs que expone una API 100% compatible con OpenAI. Cualquier aplicación que use la API de OpenAI puede apuntar a Synapse sin cambiar código — solo cambiando `base_url` y `api_key`.

Synapse se encarga de:
- **Ruteo**: dirigir cada request al provider y modelo óptimo
- **Smart Routes**: clasificar la intención del mensaje y elegir el modelo automáticamente
- **Fallback**: si un provider falla, probar el siguiente en la cadena
- **Métricas**: registrar uso, latencia, costo y tokens por request
- **Audio**: STT (Whisper local) y TTS (macOS) con la misma API key

## Conexión rápida

```
Base URL:  http://100.72.169.113:8800
API Key:   (solicitar al admin — formato syn-XXXXX)
```

### Ejemplo: Chat completion (Python)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://100.72.169.113:8800/v1",
    api_key="syn-TU-KEY-AQUI",
)

response = client.chat.completions.create(
    model="auto",  # Smart Route — Synapse elige el modelo
    messages=[{"role": "user", "content": "Hola, ¿cómo estás?"}],
)
print(response.choices[0].message.content)
```

### Ejemplo: Streaming

```python
stream = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Explica qué es una API REST"}],
    stream=True,
)
for chunk in stream:
    content = chunk.choices[0].delta.content or ""
    print(content, end="", flush=True)
```

### Ejemplo: Modelo específico

```python
# Usar un modelo específico (bypass Smart Route)
response = client.chat.completions.create(
    model="llama3.1:8b",       # Ollama local
    messages=[{"role": "user", "content": "Hola"}],
)

# Otros ejemplos de modelos:
# model="gpt-4o"               → OpenAI
# model="claude-sonnet-4-6"    → Anthropic
# model="gemini-2.5-flash"     → Google
# model="llama-3.3-70b-versatile" → Groq (rápido)
# model="sonar-pro"            → Perplexity (con búsqueda web)
# model="deepseek-r1:32b"      → Ollama local (razonamiento)
```

### Ejemplo: curl

```bash
curl http://100.72.169.113:8800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer syn-TU-KEY-AQUI" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "Hola"}]
  }'
```

### Ejemplo: JavaScript/Node.js

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://100.72.169.113:8800/v1',
  apiKey: 'syn-TU-KEY-AQUI',
});

const response = await client.chat.completions.create({
  model: 'auto',
  messages: [{ role: 'user', content: 'Hola' }],
});
console.log(response.choices[0].message.content);
```

## Cómo funciona el modelo "auto"

Cuando envías `model: "auto"`, Synapse activa un **Smart Route**:

1. Un clasificador local rápido (llama3.1:8b) lee el mensaje del usuario
2. Detecta la **intención** (medicina, coding, razonamiento, etc.)
3. Rutea al modelo óptimo asignado a esa intención
4. Si falla, intenta el siguiente modelo en la cadena (fallback)
5. Si toda la cadena de la intención falla, cae al **default chain** como último recurso

Cada API key puede tener un Smart Route diferente asignado, permitiendo perfiles distintos por servicio.

### Modelos exclusivos de un provider

Algunos modelos solo existen en un provider (ej: `sonar-pro` en Perplexity). Synapse tiene rutas explícitas que envían estos modelos directo al provider correcto, sin pasar por la cadena dinámica.

## Parámetros soportados

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `model` | string | Nombre del modelo o `"auto"` para Smart Route |
| `messages` | array | Array de `{role, content}` (system, user, assistant) |
| `stream` | bool | `true` para respuesta en streaming (SSE) |
| `temperature` | float | 0.0 - 2.0 (default del modelo) |
| `max_tokens` | int | Límite de tokens de respuesta |
| `top_p` | float | Nucleus sampling |
| `stop` | string/array | Secuencias de parada |

## Audio (STT / TTS)

### Transcripción (Speech-to-Text)

```python
with open("audio.wav", "rb") as f:
    transcript = client.audio.transcriptions.create(
        model="whisper-large-v3",  # o whisper-medium, whisper-base
        file=f,
        language="es",
    )
print(transcript.text)
```

### Texto a voz (Text-to-Speech)

```python
response = client.audio.speech.create(
    model="tts-local",
    input="Hola, esta es una prueba de síntesis de voz.",
    voice="paulina",  # paulina, monica, jorge, juan, allison, samantha, tom
)
response.stream_to_file("output.wav")
```

## Providers disponibles

| Provider | Tipo | Modelos | Notas |
|----------|------|---------|-------|
| Ollama | Local | 7 | GPU Metal, sin costo, privacidad total |
| Groq | Cloud | 18 | Ultra-rápido, gratis con límites |
| NVIDIA NIM | Cloud | 186 | Catálogo más amplio |
| Anthropic | Cloud | 9 | Claude (mejor razonamiento) |
| OpenAI | Cloud | 121 | GPT, o-series, DALL-E, TTS |
| Google Gemini | Cloud | 45 | Gemini, Gemma, Imagen, Veo |
| Perplexity | Cloud | 5 | Búsqueda web integrada |

**Total: 391 modelos** — ver `docs/models.md` para la lista completa.

## Errores comunes

| Error | Causa | Solución |
|-------|-------|----------|
| 401 Unauthorized | API key inválida o revocada | Verificar key con admin |
| 404 Model not found | Modelo no existe o no activado | Ver lista en `docs/models.md` |
| 503 All providers failed | Todos los fallbacks fallaron | Verificar que providers estén online |
| Respuesta vacía | Algunos modelos con max_tokens bajo | Subir `max_tokens` (especialmente deepseek-r1) |

## Admin panel

El panel de administración está en `http://100.72.169.113:8800/admin/` (requiere credenciales).

Desde ahí se puede:
- Ver estado de todos los providers
- Configurar Smart Routes e intenciones
- Generar y revocar API keys
- Comparar modelos en el Arena
- Ver analytics de uso y costos
