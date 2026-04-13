"""Phase 0 validation: test litellm Router against each provider.

Run: python test_litellm_router.py
"""

import asyncio
import sys
import time

from dotenv import load_dotenv
load_dotenv()

from synapse.database import init_db, async_session
from synapse.services.litellm_router import build_router


TEST_CASES = [
    # (display_name, model, messages, extra_kwargs)
    ("Ollama (medgemma)", "ollama/alibayram/medgemma:4b",
     [{"role": "user", "content": "Di hola en una palabra"}], {}),

    ("MLX Phi-4", "mlx-community/phi-4-4bit",
     [{"role": "user", "content": "Di hola en una palabra"}], {}),

    ("MLX Gemma 4B Vision", "mlx-community/gemma-4-e4b-it-4bit",
     [{"role": "user", "content": "Di hola en una palabra"}], {}),

    ("Anthropic Haiku", "anthropic/claude-haiku-4-5-20251001",
     [{"role": "user", "content": "Di hola en una palabra"}], {"max_tokens": 20}),

    ("Gemini Flash", "gemini/gemini-2.5-flash",
     [{"role": "user", "content": "Di hola en una palabra"}], {"max_tokens": 20}),

    ("Groq Llama", "groq/llama-3.3-70b-versatile",
     [{"role": "user", "content": "Di hola en una palabra"}], {"max_tokens": 20}),

    ("MiniMax M2.7", "minimax/MiniMax-M2.7",
     [{"role": "user", "content": "Di hola en una palabra"}], {"max_tokens": 50}),
]

# Optional: skip expensive or unreliable providers
SKIP = set()


async def main():
    print("Initializing DB and building litellm Router...")
    await init_db()

    async with async_session() as db:
        router = await build_router(db)

    print(f"\nRouter ready with {len(router.model_list)} model entries\n")
    print("-" * 70)

    passed = 0
    failed = 0

    for name, model, messages, kwargs in TEST_CASES:
        if name in SKIP:
            print(f"  SKIP  {name}")
            continue

        try:
            start = time.monotonic()
            response = await router.acompletion(
                model=model,
                messages=messages,
                **kwargs,
            )
            elapsed = time.monotonic() - start
            content = response.choices[0].message.content or ""
            tokens = getattr(response.usage, "total_tokens", "?")
            print(f"  OK    {name:25s} | {elapsed:.1f}s | {tokens} tok | {content[:50]}")
            passed += 1
        except Exception as e:
            elapsed = time.monotonic() - start
            print(f"  FAIL  {name:25s} | {elapsed:.1f}s | {e}")
            failed += 1

    print("-" * 70)
    print(f"\nResults: {passed} passed, {failed} failed out of {passed + failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
