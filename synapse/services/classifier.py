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

    # Resolve classifier model
    classifier_model = smart_route.classifier_model
    provider = await _get_classifier_provider(classifier_model, db)

    try:
        start = time.monotonic()

        call_kwargs = {
            "model": f"ollama/{classifier_model}" if provider and provider.is_local else classifier_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 20,
            "temperature": 0.0,
        }
        if provider and provider.base_url:
            call_kwargs["api_base"] = provider.base_url

        response = await litellm.acompletion(**call_kwargs)
        elapsed = int((time.monotonic() - start) * 1000)

        raw = response.choices[0].message.content.strip().lower()
        # Clean up: remove punctuation, take first word
        intent_name = raw.split()[0].strip(".,;:!?\"'") if raw else ""

        logger.info(
            f"Classified as '{intent_name}' in {elapsed}ms "
            f"(classifier: {classifier_model})"
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
        logger.error(f"Classification failed: {e}, using default chain")
        return "default", default_chain


async def _get_classifier_provider(
    model: str, db: AsyncSession
) -> Provider | None:
    """Find the provider for the classifier model (usually Ollama)."""
    result = await db.execute(
        select(Provider).where(
            Provider.name == "ollama", Provider.is_enabled.is_(True)
        )
    )
    return result.scalar_one_or_none()
