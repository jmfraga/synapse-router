#!/usr/bin/env python3
"""OpenClaw Arena Runner — Gemma 4 31B (NVIDIA) vs Nemotron 30B (MLX local)."""

import json
import time
import requests
import sqlite3
from datetime import datetime

SYNAPSE_DB = "synapse.db"

# Models to test
MODELS = [
    {
        "name": "gemma-4-31b-it",
        "provider": "nvidia",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model_id": "google/gemma-4-31b-it",
        "api_key": None,  # loaded from DB
    },
    {
        "name": "nemotron-30b-a3b",
        "provider": "mlx-local",
        "base_url": "http://localhost:8085/v1",
        "model_id": "mlx-community/NVIDIA-Nemotron-3-Nano-30B-A3B-4bit",
        "api_key": "not-needed",
    },
]

# 6 OpenClaw test cases
TESTS = [
    {
        "name": "PM Delegación",
        "category": "openclaw",
        "prompt": "Eres PM, el Project Manager de un sistema multi-agente. Recibes este mensaje del usuario:\n\n'Necesito que Iris le mande un recordatorio a mi esposa por WhatsApp de la cita con el cardiólogo mañana a las 4pm, que Atlas cree una tarea en el Kanban para revisar los backups del servidor, y que CHAPPiE revise si el endpoint /api/health del gateway está respondiendo correctamente.'\n\nTienes estas herramientas:\n- sessions_send(agent_id: str, message: str) -> dict: Envía mensaje a otro agente\n- sessions_spawn(agent_id: str, task: str) -> dict: Crea subagente temporal\n- kanban_create_task(title: str, assignee: str, priority: str) -> dict: Crea tarea\n\nPlanifica la delegación: decide qué agente maneja cada solicitud, en qué orden, y genera las llamadas a herramientas en JSON. Explica brevemente tu razonamiento.",
    },
    {
        "name": "Iris Conversación",
        "category": "openclaw",
        "prompt": "Eres Iris, una asistente personal amable y eficiente que atiende por WhatsApp. El usuario te envía este audio transcrito:\n\n'Oye Iris, fíjate que ando buscando un restaurante italiano por la zona de Polanco para cenar el viernes con mi esposa, somos dos personas, algo no tan caro pero que esté bonito. Y aparte recuérdame que tengo que pasar por la farmacia a comprar el medicamento que me recetó el doctor, creo que era losartán.'\n\nResponde de forma natural, cálida y concisa (máximo 150 palabras). Separa las dos solicitudes: la del restaurante (ofrece ayuda concreta) y el recordatorio (confírmalo). Usa español mexicano coloquial pero profesional.",
    },
    {
        "name": "Atlas DevOps + Kanban",
        "category": "openclaw",
        "prompt": "Eres Atlas, agente de DevOps e infraestructura. Tienes estas herramientas:\n- kanban_list_tasks(status: str, assignee: str) -> list[dict]: Lista tareas\n- kanban_update_task(task_id: str, status: str, notes: str) -> dict: Actualiza tarea\n- shell_exec(command: str) -> dict: Ejecuta comando en servidor (solo lectura)\n- http_check(url: str, timeout: int) -> dict: Verifica endpoint\n\nRecibiste esta instrucción del PM:\n'Revisa el estado de los servicios de OpenClaw en la RPi5. Verifica que el gateway (puerto 18789), el hub (puerto 8080) y contacts (puerto 3335) estén respondiendo. Si alguno falla, crea una tarea de alta prioridad en el Kanban. Después actualiza la tarea OC-147 como completada.'\n\nMuestra tu plan paso a paso y las llamadas a herramientas en JSON.",
    },
    {
        "name": "Argus Log Analysis",
        "category": "openclaw",
        "prompt": "Eres Argus, el agente de QA y monitoreo. Analiza este fragmento de logs del gateway de OpenClaw y genera un reporte:\n\n```\n2026-04-02 02:00:01 [INFO] cron-argus: Starting daily health check\n2026-04-02 02:00:03 [OK] gateway: 18789 responding (latency: 45ms)\n2026-04-02 02:00:03 [OK] hub: 8080 responding (latency: 120ms)\n2026-04-02 02:00:04 [WARN] contacts: 3335 responding (latency: 2340ms)\n2026-04-02 02:00:05 [OK] ollama: 11434 responding, models loaded: 2\n2026-04-02 02:00:06 [ERROR] session iris-assistant: context_tokens=127450/128000 (99.6%) — CRITICAL\n2026-04-02 02:00:06 [WARN] session pm: context_tokens=98000/128000 (76.6%)\n2026-04-02 02:00:07 [OK] session atlas: context_tokens=12000/128000 (9.4%)\n2026-04-02 02:00:07 [WARN] memory-core: disk usage 89% on /home/jmfraga/.openclaw\n2026-04-02 02:00:08 [ERROR] whatsapp-channel: last_message_received=6h ago — possible disconnect\n```\n\nGenera: 1) Resumen ejecutivo, 2) Problemas críticos con prioridad, 3) Acciones recomendadas para cada problema, 4) Si alguno requiere escalamiento al owner.",
    },
    {
        "name": "CHAPPiE Code Review",
        "category": "openclaw",
        "prompt": "Eres CHAPPiE, agente desarrollador. Revisa este fragmento de código Python de un endpoint del gateway de OpenClaw y señala problemas de seguridad, rendimiento y buenas prácticas:\n\n```python\n@router.post('/api/sessions/{agent_id}/send')\nasync def send_message(agent_id: str, request: Request):\n    body = await request.json()\n    message = body['message']\n    session_file = f'/home/jmfraga/.openclaw/agents/{agent_id}/sessions/current.jsonl'\n    \n    with open(session_file, 'a') as f:\n        f.write(json.dumps({'role': 'user', 'content': message, 'ts': str(datetime.now())}) + '\\n')\n    \n    cmd = f\"cd /home/jmfraga/.openclaw && node gateway.js process {agent_id} '{message}'\"\n    result = subprocess.run(cmd, shell=True, capture_output=True, timeout=30)\n    \n    return {'status': 'ok', 'response': result.stdout.decode()}\n```\n\nSé específico: señala cada issue, explica el riesgo, y proporciona el código corregido.",
    },
    {
        "name": "Phoenix Estrategia",
        "category": "openclaw",
        "prompt": "Eres Phoenix, agente de marketing y estrategia de contenido. El usuario te dice por WhatsApp:\n\n'Phoenix, necesito que me ayudes a armar una estrategia de contenido para la cuenta de Instagram de SimAcademy. Es una academia de simulación médica en México, nuestro público son médicos residentes y estudiantes de medicina. Tenemos un presupuesto limitado y queremos crecer de 500 a 2000 seguidores en 3 meses. Dame un plan concreto con ideas de posts para las primeras 2 semanas.'\n\nResponde con un plan estructurado pero conciso. Incluye: estrategia general (3-4 líneas), calendario de las 2 semanas con tipo de contenido y copy sugerido para cada post. Usa español mexicano.",
    },
]


def load_nvidia_key():
    conn = sqlite3.connect(SYNAPSE_DB)
    cur = conn.cursor()
    cur.execute("SELECT api_key_value FROM providers WHERE name = 'nvidia'")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def call_model(model_cfg, prompt, max_tokens=1500, temperature=0.7):
    headers = {"Content-Type": "application/json"}
    if model_cfg["api_key"]:
        headers["Authorization"] = f"Bearer {model_cfg['api_key']}"

    payload = {
        "model": model_cfg["model_id"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    t0 = time.time()
    try:
        resp = requests.post(
            f"{model_cfg['base_url']}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        data = resp.json()

        if "error" in data:
            return {
                "status": "error",
                "error": data["error"],
                "total_time_ms": elapsed_ms,
            }

        choice = data["choices"][0]
        usage = data.get("usage", {})
        completion_tokens = usage.get("completion_tokens", 0)
        tps = completion_tokens / (elapsed_ms / 1000) if elapsed_ms > 0 else 0

        return {
            "status": "success",
            "response_text": choice["message"]["content"],
            "completion_tokens": completion_tokens,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "total_time_ms": elapsed_ms,
            "tokens_per_sec": round(tps, 1),
            "finish_reason": choice.get("finish_reason", ""),
        }
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        return {
            "status": "error",
            "error": str(e),
            "total_time_ms": elapsed_ms,
        }


def save_to_arena_db(battle_id, model_cfg, result):
    conn = sqlite3.connect(SYNAPSE_DB)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO arena_results
           (battle_id, provider, model, ttft_ms, tokens_per_sec,
            completion_tokens, total_time_ms, cost_usd, response_text, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            battle_id,
            model_cfg["provider"],
            model_cfg["name"],
            0,
            result.get("tokens_per_sec", 0),
            result.get("completion_tokens", 0),
            result.get("total_time_ms", 0),
            0.0,
            result.get("response_text", result.get("error", "")),
            result["status"],
            datetime.now().isoformat(),
        ),
    )
    result_id = cur.lastrowid
    conn.commit()
    conn.close()
    return result_id


def create_battle(test):
    conn = sqlite3.connect(SYNAPSE_DB)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO arena_battles (prompt, category, temperature, max_tokens, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (test["prompt"], test["category"], 0.7, 1500, datetime.now().isoformat()),
    )
    battle_id = cur.lastrowid
    conn.commit()
    conn.close()
    return battle_id


def main():
    # Load NVIDIA key
    nvidia_key = load_nvidia_key()
    if not nvidia_key:
        print("ERROR: No NVIDIA API key found in synapse.db")
        return
    MODELS[0]["api_key"] = nvidia_key

    # Verify Nemotron is accessible
    try:
        r = requests.get("http://localhost:8085/v1/models", timeout=5)
        print(f"✓ Nemotron MLX: {r.status_code}")
    except Exception as e:
        print(f"✗ Nemotron MLX not accessible: {e}")
        return

    print(f"\n{'='*70}")
    print(f"OpenClaw Arena — {len(TESTS)} tests × {len(MODELS)} models")
    print(f"{'='*70}\n")

    results_summary = []

    for i, test in enumerate(TESTS, 1):
        print(f"\n--- Test {i}/6: {test['name']} ---")
        battle_id = create_battle(test)
        print(f"  Battle ID: {battle_id}")

        test_results = {"test": test["name"]}

        for model in MODELS:
            print(f"  → {model['name']}...", end=" ", flush=True)
            result = call_model(model, test["prompt"])
            save_to_arena_db(battle_id, model, result)

            if result["status"] == "success":
                print(
                    f"✓ {result['completion_tokens']} tok, "
                    f"{result['tokens_per_sec']} tok/s, "
                    f"{result['total_time_ms']}ms"
                )
                test_results[model["name"]] = {
                    "tokens": result["completion_tokens"],
                    "tps": result["tokens_per_sec"],
                    "time_ms": result["total_time_ms"],
                    "response_preview": result["response_text"][:200],
                }
            else:
                print(f"✗ {result.get('error', 'unknown error')}")
                test_results[model["name"]] = {"error": result.get("error")}

        results_summary.append(test_results)

    # Print summary
    print(f"\n{'='*70}")
    print("RESUMEN")
    print(f"{'='*70}")
    print(f"{'Test':<25} {'Gemma4 tok/s':>14} {'Gemma4 ms':>10} {'Nemotron tok/s':>14} {'Nemotron ms':>12}")
    print("-" * 75)
    for r in results_summary:
        g = r.get("gemma-4-31b-it", {})
        n = r.get("nemotron-30b-a3b", {})
        print(
            f"{r['test']:<25} "
            f"{g.get('tps', 'ERR'):>14} "
            f"{g.get('time_ms', 'ERR'):>10} "
            f"{n.get('tps', 'ERR'):>14} "
            f"{n.get('time_ms', 'ERR'):>12}"
        )

    # Save full results
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = f"arena/openclaw_results_{ts}.json"
    import os
    os.makedirs("arena", exist_ok=True)
    with open(outfile, "w") as f:
        json.dump(results_summary, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en: {outfile}")


if __name__ == "__main__":
    main()
