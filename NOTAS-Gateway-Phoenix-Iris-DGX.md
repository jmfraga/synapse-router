# Synapse como gateway de Phoenix/Iris + DGX Spark — nota de dirección

> Lluvia de ideas (2026-06-28), **SIN decidir**. Atado a la decisión de comprar el **DGX Spark
> (ASUS Ascent GX10, GB10, ~128 GB unificada, CUDA)** para inferencia local. Esta nota existe para
> que una futura sesión `synapse-ops` arranque con contexto. No implementar nada todavía.

## El objetivo que se está evaluando
Que **Phoenix** (agente de grupos WhatsApp) e **Iris** (agente 1:1 de pacientes) puedan elegir
**modelo por conversación/grupo** (además del SOUL por grupo que Phoenix ya tiene) y, eventualmente,
correr parte de la inferencia **local en el DGX**. La jugada limpia es **NO meter SDKs de N
proveedores en cada agente**, sino que los agentes hablen **un solo endpoint OpenAI-compatible
(Synapse)** y el "modelo de elección" sea solo un **string de route/modelo**. Si Synapse se muda al
DGX, los modelos locales grandes entran como **un provider más** sin tocar a los agentes.

**El problema:** para que ese camino sea viable, Synapse tiene que crecer en 3 ejes. Hoy
(por confirmar en esta sesión) Synapse es principalmente routing de **texto**.

## Los 3 ejes (en orden de dificultad)

### 1. Texto / routing — FÁCIL
"Modelo por grupo" = el agente pasa un string a Synapse. Esto Synapse ya lo hace. Solo faltaría que
los agentes expongan en su UI un select con los modelos/routes que Synapse publica.

### 2. Multimodal (imagen + PDF) — MEDIO/DIFÍCIL
El contenido multimodal vive **dentro** del payload de chat, así que sí tiene sentido que pase por
Synapse. Dos sub-capas:
- **Imágenes** — manejable: en OpenAI-compatible van como `image_url` (base64/URL); Synapse solo
  las deja pasar al provider con visión (Qwen-VL local / Sonnet).
- **PDF — el nudo.** No hay formato universal:
  - Anthropic usa **document blocks** (`pdf_input`, renderiza páginas internamente).
  - Modelos abiertos / OpenAI-compatible **NO**: esperan que ya hayas hecho `PDF → imágenes`.
  - ⇒ "Synapse multimodal" significa **traducir content-blocks según destino**: a Anthropic →
    document block nativo; a modelo local → convertir PDF a imágenes primero. **Esa traducción es el
    trabajo real, no el routing.**

> ⚠️ Trade-off que esto destapa: Phoenix/Iris hoy usan **SDK nativo Anthropic** y de ahí sacan
> `pdf_input` nativo + **prompt caching fino** + tool-use en formato Anthropic. Pasarlos a
> OpenAI-compatible vía Synapse **pierde** esas features (caching lo gestiona Synapse o se va).
> Por eso el plan provisional es **híbrido**: flujos con PDF en nativo-Anthropic, el resto por Synapse.

### 3. Audio (STT/TTS) — EJE DISTINTO, otro boleto
TTS/STT **no son content-blocks**; son un pipeline que **envuelve** la llamada:
`nota de voz WA → STT → texto → modelo → texto → TTS → audio`. Por eso no "pasa por Synapse" igual
que la imagen. Bifurcación:
- **(A)** Synapse también expone `/v1/audio/transcriptions` + `/v1/audio/speech` (todo bajo un
  gateway, pero más superficie que mantener).
- **(B, preferida)** Audio como servicio aparte: los agentes llaman directo al server de audio (hoy
  `mlx-audio :8090` en el M4 — Parakeet/Whisper STT + Sohee TTS), y **solo el chat** va por Synapse.
  Menos acoplado.
- Nota: Synapse ya hace **sanitización de texto-para-TTS** (limpiar la salida ≠ servir STT/TTS).
- **DGX = buena noticia para audio:** CUDA corre **faster-whisper** (STT) + TTS (XTTS/Piper) mucho
  mejor que MLX. Candidato a mover `mlx-audio` del M4 al DGX si se centraliza inferencia ahí.

## Para la sesión synapse-ops — qué auditar/diseñar (NO implementar aún)
1. **¿Qué tan multimodal es Synapse HOY?** ¿Pasa `image_url` end-to-end a un provider con visión?
   ¿Hace algo con PDF/document blocks o los rechaza?
2. **¿Qué costaría la capa de traducción de content-blocks** (Anthropic document ↔ imágenes para
   modelos locales)? Bosquejo de diseño, no código.
3. **Audio:** decidir A vs B arriba; si B, solo documentar el contrato del server de audio.
4. **Caching/PDF:** confirmar el plan híbrido (qué flujos se quedan nativo-Anthropic).
5. Cruzar todo esto con **`Propuestas-Fable.md`** (root de este repo) — varias propuestas de
   eficiencia/confiabilidad pueden tocar las mismas piezas; aprovechar para no hacer doble trabajo.

## Contexto en memoria (M4)
- `project_phoenix_iris_dgx_spark.md` — el análisis completo (veredicto híbrido Phoenix-sí / Iris-con-cuidado).
- `project_synapse_router.md`, `project_phoenix_iris_ux_parity.md`, `project_m4_audio_server.md`.
