"""litellm custom callback — writes usage metrics to the same usage_logs table."""

import logging
import time

import litellm
from litellm.integrations.custom_logger import CustomLogger

from synapse.database import async_session
from synapse.models import UsageLog

logger = logging.getLogger("synapse.litellm_callback")


class SynapseUsageCallback(CustomLogger):
    """Logs every litellm completion (success or failure) to our SQLite DB."""

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        try:
            latency_ms = int((end_time - start_time).total_seconds() * 1000)

            # Extract provider and model from litellm metadata
            litellm_params = kwargs.get("litellm_params", {})
            model = kwargs.get("model", "")
            # litellm_params.custom_llm_provider gives the provider name
            provider = litellm_params.get("custom_llm_provider", "")
            if not provider and "/" in model:
                provider = model.split("/")[0]

            # Token usage
            usage = getattr(response_obj, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or 0

            # Cost
            cost = 0.0
            try:
                cost = litellm.completion_cost(completion_response=response_obj)
            except Exception:
                pass

            # API key ID from metadata (set by completions_v2 handler)
            metadata = kwargs.get("metadata", {}) or {}
            api_key_id = metadata.get("api_key_id", 0)

            log = UsageLog(
                api_key_id=api_key_id,
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                cost_usd=cost,
                status="success",
                route_path=f"v2/{provider}/{model}",
                smart_route_name="",
                intent="",
            )

            async with async_session() as db:
                db.add(log)
                await db.commit()

        except Exception as e:
            logger.warning("Failed to log success event: %s", e)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        try:
            latency_ms = int((end_time - start_time).total_seconds() * 1000)

            litellm_params = kwargs.get("litellm_params", {})
            model = kwargs.get("model", "")
            provider = litellm_params.get("custom_llm_provider", "")
            if not provider and "/" in model:
                provider = model.split("/")[0]

            metadata = kwargs.get("metadata", {}) or {}
            api_key_id = metadata.get("api_key_id", 0)

            log = UsageLog(
                api_key_id=api_key_id,
                provider=provider,
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=latency_ms,
                cost_usd=0.0,
                status="error",
                route_path=f"v2/{provider}/{model}",
                smart_route_name="",
                intent="",
            )

            async with async_session() as db:
                db.add(log)
                await db.commit()

        except Exception as e:
            logger.warning("Failed to log failure event: %s", e)
