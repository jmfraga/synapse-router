"""QA runner — sends test prompts through the classifier and evaluates results."""

import asyncio
import json
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.database import async_session
from synapse.models import SmartRoute
from synapse.services.classifier import classify_intent
from synapse.qa.loader import TestCase

logger = logging.getLogger("synapse.qa")


async def run_classifier_test(case: TestCase, db: AsyncSession) -> TestCase:
    """Run a single classifier test: send prompt, check detected intent."""
    # Find the smart route
    result = await db.execute(
        select(SmartRoute).where(SmartRoute.name == case.route)
    )
    smart_route = result.scalar_one_or_none()

    if not smart_route:
        case.detected_intent = f"ERROR: route '{case.route}' not found"
        case.passed = False
        return case

    if not smart_route.is_enabled:
        case.detected_intent = f"ERROR: route '{case.route}' disabled"
        case.passed = False
        return case

    start = time.monotonic()
    intent_name, chain = await classify_intent(case.prompt, smart_route, db)
    elapsed = int((time.monotonic() - start) * 1000)

    case.detected_intent = intent_name
    case.latency_ms = elapsed
    case.passed = intent_name == case.expected_intent

    # Record which model/provider was in the chain
    if chain:
        case.provider_used = chain[0].get("provider", "")
        case.model_used = chain[0].get("model", "")

    return case


async def run_classifier_batch(cases: list[TestCase]) -> list[TestCase]:
    """Run all classifier tests sequentially (classifier uses local model)."""
    async with async_session() as db:
        results = []
        for case in cases:
            result = await run_classifier_test(case, db)
            results.append(result)
            status = "✓" if result.passed else "✗"
            logger.info(
                f"  {status} {result.id}: "
                f"expected={result.expected_intent}, "
                f"got={result.detected_intent} "
                f"({result.latency_ms}ms)"
            )
    return results


def build_confusion_matrix(results: list[TestCase]) -> dict:
    """Build confusion matrix from test results."""
    # Collect all intents (expected + detected)
    all_intents = sorted(set(
        [r.expected_intent for r in results] +
        [r.detected_intent for r in results if not r.detected_intent.startswith("ERROR")]
    ))

    matrix = {expected: {detected: 0 for detected in all_intents} for expected in all_intents}
    for r in results:
        if r.detected_intent.startswith("ERROR"):
            continue
        if r.expected_intent in matrix and r.detected_intent in matrix[r.expected_intent]:
            matrix[r.expected_intent][r.detected_intent] += 1

    return matrix


def build_report(results: list[TestCase]) -> dict:
    """Build a full QA report from test results."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    errors = sum(1 for r in results if r.detected_intent.startswith("ERROR"))

    # Per-route stats
    routes = {}
    for r in results:
        if r.route not in routes:
            routes[r.route] = {"total": 0, "passed": 0, "errors": 0}
        routes[r.route]["total"] += 1
        if r.passed:
            routes[r.route]["passed"] += 1
        if r.detected_intent.startswith("ERROR"):
            routes[r.route]["errors"] += 1

    for route_stats in routes.values():
        t = route_stats["total"]
        route_stats["accuracy"] = round(route_stats["passed"] / t * 100, 1) if t else 0

    # Per-intent stats
    intents = {}
    for r in results:
        key = f"{r.route}/{r.expected_intent}"
        if key not in intents:
            intents[key] = {"total": 0, "passed": 0}
        intents[key]["total"] += 1
        if r.passed:
            intents[key]["passed"] += 1

    for intent_stats in intents.values():
        t = intent_stats["total"]
        intent_stats["accuracy"] = round(intent_stats["passed"] / t * 100, 1) if t else 0

    # Misclassifications
    misses = [
        {
            "id": r.id,
            "route": r.route,
            "prompt": r.prompt[:80],
            "expected": r.expected_intent,
            "got": r.detected_intent,
        }
        for r in results if not r.passed
    ]

    # Confusion matrices per route
    confusion = {}
    for route_name in routes:
        route_results = [r for r in results if r.route == route_name]
        confusion[route_name] = build_confusion_matrix(route_results)

    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed - errors,
            "errors": errors,
            "accuracy": round(passed / total * 100, 1) if total else 0,
        },
        "by_route": routes,
        "by_intent": intents,
        "misclassifications": misses,
        "confusion_matrices": confusion,
    }
