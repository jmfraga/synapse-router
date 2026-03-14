"""Load QA test cases from Markdown files with YAML frontmatter."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TestCase:
    id: str
    route: str
    expected_intent: str
    prompt: str
    category: str = ""
    language: str = "es"
    description: str = ""
    # Filled after running
    detected_intent: str = ""
    model_used: str = ""
    provider_used: str = ""
    latency_ms: int = 0
    passed: bool = False


def parse_test_file(path: Path) -> list[TestCase]:
    """Parse a Markdown test file. Supports multiple test cases per file."""
    text = path.read_text(encoding="utf-8")

    # Split on YAML frontmatter boundaries
    parts = re.split(r"^---\s*$", text, flags=re.MULTILINE)
    if len(parts) < 3:
        return []

    cases = []
    # Handle files with multiple cases (--- separated)
    i = 1
    while i < len(parts) - 1:
        front = parts[i].strip()
        body = parts[i + 1].strip()
        i += 2

        try:
            meta = yaml.safe_load(front)
        except yaml.YAMLError:
            continue

        if not meta or not isinstance(meta, dict):
            continue

        # Extract prompt from body (after "# Prompt" header or first line)
        prompt = ""
        for line in body.split("\n"):
            line = line.strip()
            if line.startswith("#"):
                continue
            if line:
                # Remove surrounding quotes
                prompt = line.strip("\"'")
                break

        if not prompt:
            continue

        cases.append(TestCase(
            id=meta.get("id", path.stem),
            route=meta.get("route", ""),
            expected_intent=meta.get("expected_intent", ""),
            prompt=prompt,
            category=meta.get("category", ""),
            language=meta.get("language", "es"),
            description=meta.get("description", ""),
        ))

    return cases


def load_tests(
    tests_dir: Path,
    route_filter: str = "",
    category_filter: str = "",
) -> list[TestCase]:
    """Load all test cases, optionally filtered by route or category."""
    cases = []
    for path in sorted(tests_dir.glob("*.md")):
        cases.extend(parse_test_file(path))

    if route_filter:
        cases = [c for c in cases if c.route == route_filter]
    if category_filter:
        cases = [c for c in cases if c.category == category_filter]

    return cases
