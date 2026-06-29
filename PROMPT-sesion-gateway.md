# Prompt para arrancar la sesión synapse-ops (gateway multimodal/audio para Phoenix/Iris + DGX)

Copia esto al iniciar la sesión:

---

Lanza el agente **synapse-ops**. Antes de proponer nada, lee dos archivos del root de
`/Users/jmfraga/synapse-router`:

1. **`NOTAS-Gateway-Phoenix-Iris-DGX.md`** — la dirección que estamos evaluando: usar Synapse como
   gateway único OpenAI-compatible para que Phoenix e Iris elijan modelo por grupo, con miras a
   inferencia local en el DGX Spark. Incluye los 3 ejes (texto/routing, multimodal imagen+PDF, audio
   STT/TTS) y el trade-off de perder features nativas de Anthropic (pdf_input, prompt caching).

2. **`Propuestas-Fable.md`** — las propuestas pendientes de la auditoría Fable de este repo.

Tu tarea en esta sesión es **diseño/auditoría, NO implementar**:

- Audita **qué tan multimodal es Synapse hoy**: ¿pasa `image_url` end-to-end a un provider con
  visión? ¿qué hace con PDF / document blocks?
- Bosqueja qué costaría la **capa de traducción de content-blocks** (Anthropic document ↔ imágenes
  para modelos locales).
- Decide el camino de **audio** (A: Synapse expone `/v1/audio/*` vs B: servicio aparte tipo
  `mlx-audio`) y justifica.
- **Cruza con `Propuestas-Fable.md`**: marca qué propuestas tocan estas mismas piezas para no hacer
  doble trabajo, y cuáles conviene hacer antes/junto.
- Entrega un plan por fases (qué se hace solo si llega el DGX vs qué se puede adelantar), sin tocar
  código todavía.

Mantén el principio: **Phoenix e Iris siguen siendo agentes delgados** (un endpoint
OpenAI-compatible), la complejidad vive en Synapse. Nada de fusionar agentes ni cambiar su filosofía.

---
