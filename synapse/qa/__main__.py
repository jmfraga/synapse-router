"""Synapse QA CLI — run classifier and pipeline tests.

Usage:
    python -m synapse.qa classify
    python -m synapse.qa classify --route openclaw-smart
    python -m synapse.qa classify --route openclaw-smart --category coding
    python -m synapse.qa pipeline --key syn-xxx
    python -m synapse.qa pipeline --key syn-xxx --route openclaw-smart --judge ollama/glm4:9b-chat-fp16
    python -m synapse.qa smoke --route openclaw-smart
    python -m synapse.qa smoke --route openclaw-smart --key syn-xxx
    python -m synapse.qa history
    python -m synapse.qa history --route openclaw-smart
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from synapse.qa.loader import load_tests
from synapse.qa.runner import run_classifier_batch, build_report
from synapse.qa.pipeline import run_pipeline_batch, build_pipeline_report
from synapse.qa.history import save_run, get_history, get_regression

TESTS_DIR = Path(__file__).parent / "tests"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("synapse.qa")


def print_classifier_report(report: dict, verbose: bool = False):
    """Print a formatted classifier QA report."""
    s = report["summary"]
    print(f"\n{'='*60}")
    print(f"  SYNAPSE QA — Classifier Report")
    print(f"{'='*60}")
    print(f"  Total: {s['total']}  |  Passed: {s['passed']}  |  "
          f"Failed: {s['failed']}  |  Errors: {s['errors']}")
    print(f"  Accuracy: {s['accuracy']}%")
    print(f"{'='*60}")

    # Per route
    print(f"\n  Por Ruta:")
    for route, stats in report["by_route"].items():
        bar = "█" * int(stats["accuracy"] / 5) + "░" * (20 - int(stats["accuracy"] / 5))
        print(f"    {route:<25} {bar} {stats['accuracy']}%  "
              f"({stats['passed']}/{stats['total']})")

    # Per intent
    if verbose:
        print(f"\n  Por Intención:")
        for intent, stats in report["by_intent"].items():
            print(f"    {intent:<35} {stats['accuracy']}%  "
                  f"({stats['passed']}/{stats['total']})")

    # Misclassifications
    if report["misclassifications"]:
        print(f"\n  Errores de clasificación:")
        for m in report["misclassifications"]:
            print(f"    ✗ [{m['route']}] \"{m['prompt']}\"")
            print(f"      esperado: {m['expected']}, obtuvo: {m['got']}")

    # Confusion matrix
    if verbose:
        for route, matrix in report["confusion_matrices"].items():
            intents = list(matrix.keys())
            if not intents:
                continue
            print(f"\n  Confusion Matrix — {route}:")
            max_len = max(len(i) for i in intents)
            header = " " * (max_len + 4) + "  ".join(f"{i[:8]:>8}" for i in intents)
            print(f"    {header}")
            for expected in intents:
                row = f"    {expected:<{max_len + 4}}"
                for detected in intents:
                    val = matrix[expected][detected]
                    if val > 0 and expected == detected:
                        row += f"  \033[32m{val:>8}\033[0m"
                    elif val > 0:
                        row += f"  \033[31m{val:>8}\033[0m"
                    else:
                        row += f"  {'.':>8}"
                print(row)

    print()


def print_pipeline_report(report: dict, verbose: bool = False):
    """Print a formatted pipeline QA report."""
    s = report["summary"]
    print(f"\n{'='*60}")
    print(f"  SYNAPSE QA — Pipeline Report")
    print(f"{'='*60}")
    print(f"  Total: {s['total']}  |  Routing OK: {s['routing_correct']}  |  "
          f"Errors: {s['errors']}")
    print(f"  Routing Accuracy: {s['routing_accuracy']}%")
    if s['avg_quality'] is not None:
        print(f"  Avg Quality: {s['avg_quality']}/5.0")
    print(f"  Avg Latency: {s['avg_latency_ms']}ms  |  Total Cost: ${s['total_cost']}")
    print(f"{'='*60}")

    # Per route
    print(f"\n  Por Ruta:")
    for route, stats in report["by_route"].items():
        acc = stats["routing_accuracy"]
        bar = "█" * int(acc / 5) + "░" * (20 - int(acc / 5))
        quality = f"  quality={stats['avg_quality']}/5" if stats.get("avg_quality") else ""
        print(f"    {route:<25} {bar} {acc}%  "
              f"({stats['routing_ok']}/{stats['total']}){quality}")

    # Details
    if verbose:
        print(f"\n  Detalle:")
        for d in report["details"]:
            icon = "✓" if d["routing_correct"] else "✗"
            line = (f"    {icon} {d['id']}: {d['detected_intent']} → "
                    f"{d['model']} ({d['latency_ms']}ms)")
            if d.get("quality_score"):
                line += f" ⭐{d['quality_score']}"
            if not d["routing_correct"]:
                line += f" [esperado: {d['expected_intent']}]"
            print(line)
            if d.get("error"):
                print(f"      ERROR: {d['error']}")

    # Misrouted
    misrouted = [d for d in report["details"] if not d["routing_correct"] and not d.get("error")]
    if misrouted:
        print(f"\n  Errores de routing:")
        for d in misrouted:
            print(f"    ✗ [{d['route']}] \"{d['prompt']}\"")
            print(f"      esperado: {d['expected_intent']}, obtuvo: {d['detected_intent']}")

    print()


def cmd_classify(args):
    """Run classifier QA tests."""
    route = args.route if args.route != "all" else ""
    cases = load_tests(TESTS_DIR, route_filter=route, category_filter=args.category)

    if not cases:
        print(f"No test cases found.", file=sys.stderr)
        if route:
            print(f"  Route filter: {route}", file=sys.stderr)
        print(f"  Tests dir: {TESTS_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Running {len(cases)} classifier tests...")
    results = asyncio.run(run_classifier_batch(cases))
    report = build_report(results)

    print_classifier_report(report, verbose=args.verbose)

    # Save to history
    run_id = save_run("classify", route, report)
    reg = get_regression("classify", route)
    if reg:
        delta = reg["delta_accuracy"]
        symbol = "📈" if delta > 0 else "📉" if delta < 0 else "➡️"
        print(f"  {symbol} vs anterior: {reg['previous_accuracy']}% → {reg['current_accuracy']}% "
              f"(Δ{delta:+.1f}%)")
        if reg["regression"]:
            print(f"  ⚠️  REGRESIÓN DETECTADA (>{5}% de caída)")
    print(f"  Historial guardado (run #{run_id})")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    if report["summary"]["accuracy"] < args.threshold:
        sys.exit(1)


def cmd_pipeline(args):
    """Run pipeline QA tests."""
    if not args.key:
        print("Error: --key is required for pipeline tests", file=sys.stderr)
        print("  Use the API key that triggers the smart route you want to test", file=sys.stderr)
        sys.exit(1)

    route = args.route if args.route != "all" else ""
    cases = load_tests(TESTS_DIR, route_filter=route, category_filter=args.category)

    if not cases:
        print(f"No test cases found.", file=sys.stderr)
        sys.exit(1)

    print(f"Running {len(cases)} pipeline tests...")
    if args.judge:
        print(f"  LLM Judge: {args.judge}")

    results = asyncio.run(run_pipeline_batch(
        cases=cases,
        api_key=args.key,
        base_url=args.url,
        judge_model=args.judge,
    ))
    report = build_pipeline_report(results)

    print_pipeline_report(report, verbose=args.verbose)

    # Save to history
    run_id = save_run("pipeline", route, report)
    reg = get_regression("pipeline", route)
    if reg:
        delta = reg["delta_accuracy"]
        symbol = "📈" if delta > 0 else "📉" if delta < 0 else "➡️"
        print(f"  {symbol} vs anterior: {reg['previous_accuracy']}% → {reg['current_accuracy']}% "
              f"(Δ{delta:+.1f}%)")
        if reg["regression"]:
            print(f"  ⚠️  REGRESIÓN DETECTADA (>{5}% de caída)")
    print(f"  Historial guardado (run #{run_id})")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    if report["summary"]["routing_accuracy"] < args.threshold:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="synapse-qa",
        description="Synapse Router QA — test classifier and pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # classify
    cls = sub.add_parser("classify", help="Test intent classification accuracy")
    cls.add_argument("--route", default="all",
                     help="Smart route name to test (default: all)")
    cls.add_argument("--category", default="",
                     help="Filter tests by category")
    cls.add_argument("--verbose", "-v", action="store_true",
                     help="Show per-intent stats and confusion matrix")
    cls.add_argument("--json", action="store_true",
                     help="Output full report as JSON")
    cls.add_argument("--threshold", type=float, default=0,
                     help="Minimum accuracy %% (exit 1 if below)")
    cls.set_defaults(func=cmd_classify)

    # pipeline
    pip = sub.add_parser("pipeline", help="Test full request pipeline (routing + response quality)")
    pip.add_argument("--key", required=True,
                     help="API key to use for requests (syn-...)")
    pip.add_argument("--route", default="all",
                     help="Smart route name to test (default: all)")
    pip.add_argument("--category", default="",
                     help="Filter tests by category")
    pip.add_argument("--judge", default="",
                     help="LLM model for quality judging (e.g. ollama/glm4:9b-chat-fp16)")
    pip.add_argument("--url", default="http://localhost:8800",
                     help="Synapse Router base URL")
    pip.add_argument("--verbose", "-v", action="store_true",
                     help="Show per-test details")
    pip.add_argument("--json", action="store_true",
                     help="Output full report as JSON")
    pip.add_argument("--threshold", type=float, default=0,
                     help="Minimum routing accuracy %% (exit 1 if below)")
    pip.set_defaults(func=cmd_pipeline)

    # smoke
    smk = sub.add_parser("smoke", help="Quick smoke test after route changes (3 tests per intent)")
    smk.add_argument("--route", required=True,
                     help="Smart route name to smoke test")
    smk.add_argument("--key", default="",
                     help="API key for pipeline mode (omit for classifier-only)")
    smk.add_argument("--threshold", type=float, default=80,
                     help="Minimum accuracy %% to pass (default: 80)")
    smk.set_defaults(func=cmd_smoke)

    # history
    hist = sub.add_parser("history", help="Show QA run history")
    hist.add_argument("--route", default="",
                      help="Filter by route")
    hist.add_argument("--type", default="", dest="run_type",
                      help="Filter by type (classify, pipeline, smoke)")
    hist.add_argument("--limit", type=int, default=20,
                      help="Number of runs to show")
    hist.set_defaults(func=cmd_history)

    args = parser.parse_args()
    args.func(args)


def cmd_smoke(args):
    """Quick smoke test — runs 3 tests per intent for a route."""
    cases = load_tests(TESTS_DIR, route_filter=args.route)

    if not cases:
        print(f"No test cases for route '{args.route}'", file=sys.stderr)
        sys.exit(1)

    # Take up to 3 per intent
    by_intent = {}
    for c in cases:
        by_intent.setdefault(c.expected_intent, []).append(c)
    smoke_cases = []
    for intent_cases in by_intent.values():
        smoke_cases.extend(intent_cases[:3])

    print(f"Smoke test: {len(smoke_cases)} tests for {args.route} "
          f"({len(by_intent)} intents, max 3 each)")

    if args.key:
        # Pipeline smoke
        results = asyncio.run(run_pipeline_batch(
            cases=smoke_cases,
            api_key=args.key,
            base_url="http://localhost:8800",
        ))
        report = build_pipeline_report(results)
        print_pipeline_report(report, verbose=True)
        accuracy = report["summary"]["routing_accuracy"]
    else:
        # Classifier-only smoke
        results = asyncio.run(run_classifier_batch(smoke_cases))
        report = build_report(results)
        print_classifier_report(report, verbose=True)
        accuracy = report["summary"]["accuracy"]

    # Save to history
    run_id = save_run("smoke", args.route, report)
    reg = get_regression("smoke", args.route)
    if reg:
        delta = reg["delta_accuracy"]
        symbol = "📈" if delta > 0 else "📉" if delta < 0 else "➡️"
        print(f"  {symbol} vs anterior: {reg['previous_accuracy']}% → {reg['current_accuracy']}% "
              f"(Δ{delta:+.1f}%)")
        if reg["regression"]:
            print(f"  ⚠️  REGRESIÓN DETECTADA")
    print(f"  Historial guardado (run #{run_id})")

    if accuracy < args.threshold:
        print(f"\n  ❌ SMOKE TEST FAILED: {accuracy}% < {args.threshold}% threshold")
        sys.exit(1)
    else:
        print(f"\n  ✅ SMOKE TEST PASSED: {accuracy}% ≥ {args.threshold}%")


def cmd_history(args):
    """Show QA run history."""
    runs = get_history(
        run_type=args.run_type,
        route_filter=args.route,
        limit=args.limit,
    )

    if not runs:
        print("No QA runs in history.")
        return

    print(f"\n{'='*70}")
    print(f"  SYNAPSE QA — History ({len(runs)} runs)")
    print(f"{'='*70}")
    print(f"  {'ID':<5} {'Type':<10} {'Route':<20} {'Acc%':<8} {'Quality':<9} {'Date'}")
    print(f"  {'-'*5} {'-'*10} {'-'*20} {'-'*8} {'-'*9} {'-'*19}")
    for r in runs:
        quality = f"{r['avg_quality']:.1f}/5" if r["avg_quality"] else "—"
        route = r["route_filter"] or "(all)"
        print(f"  {r['id']:<5} {r['run_type']:<10} {route:<20} "
              f"{r['accuracy']:<8.1f} {quality:<9} {r['created_at']}")
    print()


if __name__ == "__main__":
    main()
