"""Intent classifier — uses a fast local model to classify user messages."""

import json
import logging
import time

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.models import SmartRoute, Provider

logger = logging.getLogger("synapse.classifier")


def build_classifier_prompt(intents: list[dict]) -> str:
    """Build a classification prompt from intent definitions."""
    categories = "\n".join(
        f"- {i['name']}: {i['description']}" for i in intents
    )
    return (
        "Clasifica el siguiente mensaje del usuario en exactamente una categoría. "
        "Responde SOLO con el nombre de la categoría, sin explicación ni puntuación.\n\n"
        f"Categorías:\n{categories}\n\n"
        "Mensaje: {message}\n\n"
        "Categoría:"
    )


async def classify_intent(
    message: str,
    smart_route: SmartRoute,
    db: AsyncSession,
) -> tuple[str, list[dict]]:
    """Classify a message and return (intent_name, provider_chain).

    Returns the matched intent's chain, or the default chain if classification fails.
    """
    intents = json.loads(smart_route.intents_json)
    default_chain = json.loads(smart_route.default_chain_json)

    if not intents:
        return "default", default_chain

    # Build or use custom prompt
    prompt_template = smart_route.classifier_prompt
    if not prompt_template:
        prompt_template = build_classifier_prompt(intents)

    prompt = prompt_template.replace("{message}", message)

    # Resolve classifier chain — configured chain first, then auto fallback
    classifier_targets = await _build_classifier_chain(smart_route, db)

    for target_label, call_kwargs_base in classifier_targets:
        try:
            start = time.monotonic()

            call_kwargs = {
                **call_kwargs_base,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 20,
                "temperature": 0.0,
            }

            response = await litellm.acompletion(**call_kwargs)
            elapsed = int((time.monotonic() - start) * 1000)

            raw = response.choices[0].message.content.strip().lower()
            # Clean up: remove punctuation, take first word
            intent_name = raw.split()[0].strip(".,;:!?\"'") if raw else ""

            logger.info(
                f"Classified as '{intent_name}' in {elapsed}ms "
                f"(classifier: {target_label})"
            )

            # Find matching intent
            for intent in intents:
                if intent["name"].lower() == intent_name:
                    return intent["name"], intent["provider_chain"]

            # No exact match — try partial match
            for intent in intents:
                if intent_name in intent["name"].lower() or intent["name"].lower() in intent_name:
                    logger.info(f"Partial match: '{intent_name}' -> '{intent['name']}'")
                    return intent["name"], intent["provider_chain"]

            logger.warning(
                f"Classifier returned unknown intent '{intent_name}', "
                f"using default chain"
            )
            return "default", default_chain

        except Exception as e:
            logger.warning(f"Classifier '{target_label}' failed: {e}")
            continue

    logger.error("All classifier targets failed, using default chain")
    return "default", default_chain


async def _build_classifier_chain(
    smart_route: SmartRoute, db: AsyncSession
) -> list[tuple[str, dict]]:
    """Build an ordered list of classifier targets from the configured chain.

    Uses classifier_chain_json if configured, otherwise builds a single-entry
    chain from classifier_model (backward compat).

    Returns list of (label, call_kwargs) tuples.
    """
    chain = json.loads(smart_route.classifier_chain_json or "[]")

    # Backward compat: no chain configured, use classifier_model as Ollama
    if not chain:
        chain = [{"provider": "ollama", "model": smart_route.classifier_model}]

    targets = []
    for entry in chain:
        provider_name = entry["provider"]
        model = entry["model"]

        stmt = select(Provider).where(
            Provider.name == provider_name, Provider.is_enabled.is_(True)
        )
        result = await db.execute(stmt)
        provider = result.scalar_one_or_none()
        if not provider:
            continue

        litellm_prefix = {
            "ollama": "ollama/",
            "ollama-heavy": "ollama/",
            "groq": "groq/",
            "anthropic": "anthropic/",
            "nvidia": "nvidia_nim/",
            "openai": "",
            "gemini": "gemini/",
            "perplexity": "perplexity/",
        }.get(provider_name, f"{provider_name}/")

        kwargs = {"model": f"{litellm_prefix}{model}"}
        if provider.base_url:
            kwargs["api_base"] = provider.base_url
        if provider.api_key_value:
            kwargs["api_key"] = provider.api_key_value

        targets.append((f"{provider_name}/{model}", kwargs))

    return targets
