# Gemma 4 — Arena OpenClaw (2 abril 2026)

## Metodologia

Se evaluaron 6 modelos en 6 tareas representativas de un sistema multi-agente (orquestacion, conversacion, DevOps/tool-use, analisis de logs, code review, estrategia de contenido). Se corrieron 2 rondas con diferentes combinaciones de modelos. Cada tarea se ejecuto con los mismos parametros (temp 0.7, max_tokens ~1500-2048). Las respuestas fueron calificadas automaticamente por un LLM juez (1-5) sin conocer que modelo genero cada respuesta.

### Modelos evaluados

| Modelo | Tipo | Params activos | Ejecucion | Infra |
|--------|------|---------------|-----------|-------|
| Gemma 4 31B IT (4-bit) | Dense | 31B | Local — MLX (Apple Silicon M4, 64GB) | mlx-vlm 0.4.3 |
| Gemma 4 26B-A4B IT | MoE | 4B de 26B | API — Google AI Studio | Cloud |
| Gemma 4 E4B IT (4-bit) | Edge | 4B | Local — MLX (Apple Silicon M4, 64GB) | mlx-vlm 0.4.3 |
| MiniMax M2.7 | Dense | — | API — MiniMax | Cloud |
| Nemotron 30B-A3B (4-bit) | MoE | 3B de 30B | Local — MLX (Apple Silicon M4, 64GB) | mlx-lm 0.31.2 |
| gpt-oss-20b (4-bit) | MoE | — | Local — MLX (Apple Silicon M4, 64GB) | mlx-lm 0.31.2 |

Nota: el 26B MoE no tiene pesos MLX disponibles al momento de la prueba. Se probo via Google AI Studio, por lo que su latencia refleja red, no inferencia local.

### Tareas

1. Orquestacion multi-agente (delegacion con tool-use)
2. Conversacion natural (WhatsApp, espanol mexicano)
3. DevOps + Kanban (tool-use, verificacion de servicios)
4. Analisis de logs (QA/monitoreo, priorizacion)
5. Code review (seguridad, buenas practicas)
6. Estrategia de contenido (marketing, calendario)

## Resultados crudos

### Ronda 1: Gemma 4 familia + MiniMax

| Prueba | G4 31B (local) | G4 E4B (local) | G4 26B MoE (API) | MM M2.7 (API) |
|--------|---------------|----------------|-------------------|---------------|
| 1. Orquestacion | 35s / 5 | 9s / 3 | 99s / 5 | 20s / 5 |
| 2. Conversacion | 11s / 4 | 2s / 3 | 26s / 4 | 16s / 3 |
| 3. DevOps + Kanban | 40s / 4 | 10s / 3 | 103s / 4 | 13s / 4 |
| 4. Analisis de logs | 71s / 5 | 3s / 3 | 43s / 5 | 45s / 3 |
| 5. Code review | 134s / 3 | 28s / 2 | 58s / 5 | 44s / 3 |
| 6. Estrategia | 74s / 5 | 16s / 3 | 43s / 5 | 49s / 4 |

| Modelo | Avg Score | Avg Tiempo |
|--------|-----------|------------|
| Gemma 4 26B MoE (API) | 4.67 | 62.0s |
| Gemma 4 31B (local) | 4.33 | 60.8s |
| MiniMax M2.7 (API) | 3.67 | 31.2s |
| Gemma 4 E4B (local) | 2.83 | 11.3s |

### Ronda 2: Gemma 4 grandes + modelos locales existentes

| Prueba | G4 31B (local) | G4 26B MoE (API) | gpt-oss-20b (local) | Nemotron 30B (local) |
|--------|---------------|-------------------|--------------------|--------------------|
| 1. Orquestacion | 36s / 5 | 62s / 4 | 80s / 3 | 24s / 3 |
| 2. Conversacion | 19s / 4 | 19s / 4 | 17s / 3 | 11s / 3 |
| 3. DevOps + Kanban | 43s / 4 | 75s / 4 | error | error |
| 4. Analisis de logs | 115s / 5 | 40s / 5 | 65s / 3 | 28s / 4 |
| 5. Code review | 135s / 3 | 54s / 5 | 41s / 1 | 30s / 4 |
| 6. Estrategia | 79s / 5 | 40s / 4 | 36s / 2 | 28s / 3 |

Nota: prueba 3 ronda 2 tuvo errores 502 en gpt-oss y Nemotron (servers MLX saturados por memoria). Promedios calculados sobre pruebas completadas.

| Modelo | Avg Score | Avg Tiempo |
|--------|-----------|------------|
| Gemma 4 26B MoE (API) | 4.33 | 45.2s |
| Gemma 4 31B (local) | 4.17 | 62.2s |
| Nemotron 30B (local) | 3.33 | 23.5s |
| gpt-oss-20b (local) | 2.50 | 49.3s |

## Ranking general (ambas rondas)

| # | Modelo | Avg Score | Tipo | Notas |
|---|--------|-----------|------|-------|
| 1 | **Gemma 4 26B MoE** | **4.50** | MoE (4B activos) | Mejor calidad, pendiente correr local |
| 2 | Gemma 4 31B | 4.25 | Dense | Buena calidad, lento local (14 tok/s) |
| 3 | MiniMax M2.7 | 3.67 | Dense (API) | Bueno en conversacion, debil en tecnico |
| 4 | Nemotron 30B | 3.33 | MoE (3B activos) | Rapido local (~90 tok/s), calidad media |
| 5 | Gemma 4 E4B | 2.83 | Edge | Solo para tareas simples |
| 6 | gpt-oss-20b | 2.50 | MoE | Descartado |

## Velocidad de inferencia local (MLX, M4 64GB)

| Modelo | tok/s | RAM |
|--------|-------|-----|
| Gemma 4 E4B (edge, 4-bit) | ~76 | 5.3 GB |
| Nemotron 30B MoE (3B activos, 4-bit) | ~90 | 7.4 GB |
| Gemma 4 31B (dense, 4-bit) | ~13-14 | 18.7 GB |
| Gemma 4 26B MoE (4B activos) | no disponible local | est. ~70-90 tok/s |

## Notas

- Gemma 4 salio el 2 abril 2026, licencia Apache 2.0
- mlx-lm (0.31.2) aun no soporta model_type gemma4; mlx-vlm (0.4.3 git) si
- Ollama 0.19.0/0.20.0-rc1 no soporta runtime de Gemma 4
- Los pesos MLX del 26B MoE aun no estan disponibles en mlx-community
- La latencia del 26B via Google AI Studio incluye red — no es representativa de rendimiento local
- Con 4 modelos MLX cargados simultaneamente (~50 GB), se presentaron errores por saturacion de memoria
