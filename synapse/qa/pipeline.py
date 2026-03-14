"""Pipeline QA — test the full request flow: classify → route → model → response."""

import json
import logging
import time
from dataclasses import dataclass, field

import httpx
import litellm
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.config import get_settings
from synapse.database import async_session
from synapse.models import UsageLog, ApiKey
from synapse.qa.loader import TestCase

logger = logging.getLogger("synapse.qa")

# Disable litellm noise during QA
litellm.telemetry = False


@dataclass
class PipelineResult:
    test: TestCase
    # Routing check
    smart_route_used: str = ""
    intent_detected: str = ""
    model_used: str = ""
    provider_used: str = ""
    routing_correct: bool = False
    # Response
    response_text: str = ""
    latency_ms: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    # Quality (LLM judge)
    quality_score: float = 0.0  # 0.0 - 5.0
    quality_notes: str = ""
    # Overall
    status: str = ""  # success, error, routing_error


async def _get_api_key_for_route(route_name: str, db: AsyncSession) -> str | None:
    """Find an API key linked to a smart route, or the test key."""
    # First try to find key linked to this route's smart route
    from synapse.models import SmartRoute
    sr = (await db.execute(
        select(SmartRoute).where(SmartRoute.name == route_name)
    )).scalar_one_or_none()

    if sr:
        key = (await db.execute(
            select(ApiKey).where(
                ApiKey.smart_route_id == sr.id,
                ApiKey.is_active.is_(True),
            )
        )).scalar_one_or_none()
        if key:
            return key.key_prefix  # We need the full key, not prefix

    # Fall back to test key
    key = (await db.execute(
        select(ApiKey).where(
            ApiKey.service == "testing",
            ApiKey.is_active.is_(True),
        )
    )).scalar_one_or_none()
    return None  # Can't recover full key from hash


async def _get_last_usage_log(db: AsyncSession) -> UsageLog | None:
    """Get the most recent usage log entry."""
    result = await db.execute(
        select(UsageLog).order_by(desc(UsageLog.id)).limit(1)
    )
    return result.scalar_one_or_none()


async def run_pipeline_test(
    case: TestCase,
    api_key: str,
    base_url: str,
    judge_model: str = "",
) -> PipelineResult:
    """Run a single pipeline test through the full Synapse endpoint."""
    result = PipelineResult(test=case)

    # Determine trigger model — use "auto" for routes that use it,
    # or let the key's smart route handle it
    trigger_model = "auto"

    try:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": trigger_model,
                    "messages": [{"role": "user", "content": case.prompt}],
                    "max_tokens": 200,
                },
            )
        elapsed = int((time.monotonic() - start) * 1000)
        result.latency_ms = elapsed

        if resp.status_code != 200:
            result.status = "error"
            result.quality_notes = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return result

        data = resp.json()
        result.model_used = data.get("model", "")
        result.response_text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        usage = data.get("usage", {})
        result.tokens = usage.get("total_tokens", 0)

    except Exception as e:
        result.status = "error"
        result.quality_notes = str(e)
        return result

    # Read routing info from usage_log
    async with async_session() as db:
        log = await _get_last_usage_log(db)
        if log:
            result.smart_route_used = log.smart_route_name
            result.intent_detected = log.intent
            result.provider_used = log.provider
            result.cost_usd = log.cost_usd

    # Check routing correctness
    result.routing_correct = (
        result.smart_route_used == case.route
        and result.intent_detected == case.expected_intent
    )
    result.status = "success" if result.routing_correct else "routing_error"

    # LLM judge for response quality
    if judge_model and result.response_text:
        result.quality_score, result.quality_notes = await _judge_response(
            prompt=case.prompt,
            response=result.response_text,
            expected_intent=case.expected_intent,
            judge_model=judge_model,
        )

    return result


async def _judge_response(
    prompt: str,
    response: str,
    expected_intent: str,
    judge_model: str,
) -> tuple[float, str]:
    """Use an LLM to judge response quality on a 1-5 scale."""
    judge_prompt = f"""Evalúa la siguiente respuesta de un asistente de IA.

PREGUNTA DEL USUARIO:
{prompt}

CATEGORÍA ESPERADA: {expected_intent}

RESPUESTA DEL ASISTENTE:
{response}

Evalúa la calidad de la respuesta en una escala de 1 a 5:
1 = Respuesta incorrecta, irrelevante o dañina
2 = Parcialmente relevante pero con errores importantes
3 = Aceptable, cubre lo básico pero falta profundidad
4 = Buena respuesta, correcta y útil
5 = Excelente respuesta, completa, precisa y bien estructurada

Responde EXACTAMENTE en este formato JSON:
{{"score": <número 1-5>, "notes": "<una línea explicando la calificación>"}}"""

    try:
        resp = await litellm.acompletion(
            model=judge_model,
            messages=[{"role": "user", "content": judge_prompt}],
            max_tokens=100,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()

        # Parse JSON from response
        import re
        match = re.search(r'\{[^}]+\}', raw)
        if match:
            data = json.loads(match.group())
            return float(data.get("score", 0)), data.get("notes", "")

        # Fallback: try to extract score
        score_match = re.search(r'"score"\s*:\s*(\d)', raw)
        if score_match:
            return float(score_match.group(1)), raw[:100]

        return 0.0, f"Could not parse judge response: {raw[:100]}"

    except Exception as e:
        return 0.0, f"Judge error: {e}"


async def run_pipeline_batch(
    cases: list[TestCase],
    api_key: str,
    base_url: str = "http://localhost:8800",
    judge_model: str = "",
) -> list[PipelineResult]:
    """Run all pipeline tests sequentially."""
    results = []
    for case in cases:
        result = await run_pipeline_test(case, api_key, base_url, judge_model)
        results.append(result)

        icon = "✓" if result.routing_correct else "✗"
        quality = f" quality={result.quality_score}" if result.quality_score else ""
        logger.info(
            f"  {icon} {result.test.id}: "
            f"route={result.smart_route_used} intent={result.intent_detected} "
            f"model={result.model_used} "
            f"{result.latency_ms}ms{quality}"
        )

    return results


def build_pipeline_report(results: list[PipelineResult]) -> dict:
    """Build a full pipeline QA report."""
    total = len(results)
    routing_ok = sum(1 for r in results if r.routing_correct)
    errors = sum(1 for r in results if r.status == "error")
    has_quality = [r for r in results if r.quality_score > 0]

    avg_quality = (
        round(sum(r.quality_score for r in has_quality) / len(has_quality), 2)
        if has_quality else None
    )
    avg_latency = (
        round(sum(r.latency_ms for r in results) / total)
        if total else 0
    )
    total_cost = round(sum(r.cost_usd for r in results), 4)

    # Per route
    routes = {}
    for r in results:
        rname = r.test.route
        if rname not in routes:
            routes[rname] = {"total": 0, "routing_ok": 0, "quality_scores": []}
        routes[rname]["total"] += 1
        if r.routing_correct:
            routes[rname]["routing_ok"] += 1
        if r.quality_score > 0:
            routes[rname]["quality_scores"].append(r.quality_score)

    for stats in routes.values():
        t = stats["total"]
        stats["routing_accuracy"] = round(stats["routing_ok"] / t * 100, 1) if t else 0
        scores = stats["quality_scores"]
        stats["avg_quality"] = round(sum(scores) / len(scores), 2) if scores else None
        del stats["quality_scores"]

    # Details for failed/interesting cases
    details = []
    for r in results:
        entry = {
            "id": r.test.id,
            "route": r.test.route,
            "prompt": r.test.prompt[:80],
            "expected_intent": r.test.expected_intent,
            "detected_intent": r.intent_detected,
            "model": r.model_used,
            "latency_ms": r.latency_ms,
            "routing_correct": r.routing_correct,
        }
        if r.quality_score > 0:
            entry["quality_score"] = r.quality_score
            entry["quality_notes"] = r.quality_notes
        if r.status == "error":
            entry["error"] = r.quality_notes
        details.append(entry)

    return {
        "summary": {
            "total": total,
            "routing_correct": routing_ok,
            "routing_accuracy": round(routing_ok / total * 100, 1) if total else 0,
            "errors": errors,
            "avg_quality": avg_quality,
            "avg_latency_ms": avg_latency,
            "total_cost": total_cost,
        },
        "by_route": routes,
        "details": details,
    }
