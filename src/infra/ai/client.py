"""
Gemini AI API client implementation for batch investment analysis.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel, Field, ValidationError

from src.config import settings
from src.core.exceptions import (
    GeminiAPIError,
    GeminiAuthError,
    GeminiParsingError,
    GeminiQuotaError,
)
from src.core.models import RebalanceRecommendation
from src.utils.logger.logger import logger

MAX_RETRIES: int = 3
INITIAL_RETRY_DELAY: float = 1.0

SYSTEM_INSTRUCTION: str = (
    "You are an expert Quantitative Portfolio Manager and Asset Rebalancing "
    "Analyst. Analyze the provided target asset using real-time market metrics, "
    "historical trend data, valuation ratios (Trailing P/E, Forward P/E, P/B, PEG), "
    "fundamental health (margins, growth, debt-to-equity, dividend yield, beta), "
    "allocation gap, and structural details (TER efficiency, sector/geographic "
    "breakdowns, and top holdings concentration). Explicitly weigh sectoral and "
    "geographic allocations, expense ratios, and valuation trends to provide "
    "a deterministic, data-driven rebalancing recommendation adhering strictly "
    "to the schema without preamble or markdown."
)

SYSTEM_INSTRUCTION_BATCH: str = (
    "You are an expert Quantitative Portfolio Manager and Asset Rebalancing "
    "Analyst. Your task is to analyze all provided target assets in the "
    "portfolio context using real-time market metrics, historical trend data, "
    "valuation ratios (Trailing/Forward P/E), fundamentals, growth indicators, "
    "debt levels, and structural breakdowns (sectoral concentration, geographic "
    "distribution, top holdings). Evaluate each asset based on valuation, "
    "fundamental health, portfolio allocation gap, and ETF efficiency "
    "(TER ratios, sector/country concentration overlaps, and historical trajectory). "
    "Return a structured list containing an item for each asset symbol "
    "adhering strictly to the schema."
)


class AssetRecommendationItem(BaseModel):
    """Container linking an asset symbol to its rebalance recommendation."""

    symbol: str = Field(
        description="The exact asset ticker symbol (e.g., 'AAPL', 'EUNL.DE')."
    )
    recommendation: RebalanceRecommendation = Field(
        description="Detailed rebalancing recommendation for the asset."
    )


class BatchRebalanceRecommendations(BaseModel):
    """Schema container for batch rebalance recommendations list."""

    items: list[AssetRecommendationItem] = Field(
        description="List of recommendations for all evaluated portfolio assets."
    )


class GeminiClient:
    """Enterprise-grade client wrapper for Google Gemini AI API interactions."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
    ) -> None:
        """Initializes GeminiClient with API authentication and config."""
        raw_key: Any = settings.gemini_api_key
        resolved_key: str = api_key or (
            raw_key.get_secret_value()
            if hasattr(raw_key, "get_secret_value")
            else str(raw_key)
        )
        if not resolved_key:
            logger.error("Gemini API key is missing from environment.")
            raise GeminiAuthError("Missing GEMINI_API_KEY environment variable.")

        self.model_name: str = model_name or settings.gemini_model
        try:
            self._client: genai.Client = genai.Client(api_key=resolved_key)
        except Exception as err:
            logger.error(f"Failed to instantiate Gemini API client: {err}")
            raise GeminiAuthError(
                f"Gemini client initialization failed: {err}"
            ) from err

    def _validate_inputs(
        self,
        asset_data: dict[str, Any],
        portfolio_context: dict[str, Any],
    ) -> None:
        """Ensures incoming payload dicts contain minimum required attributes."""
        if not asset_data:
            raise ValueError("asset_data context payload cannot be empty.")
        if not portfolio_context:
            raise ValueError("portfolio_context payload cannot be empty.")

    def _handle_retry_error(
        self, err: Exception, attempt: int, label: str, delay: float
    ) -> float:
        """Handles a sync retry attempt. Returns next delay or raises."""
        if isinstance(err, APIError):
            code: int | None = getattr(err, "code", None)
            err_msg: str = str(err).lower()

            if code in (401, 403) or "auth" in err_msg:
                logger.error(f"Auth error for '{label}': {err}")
                raise GeminiAuthError(f"Authentication failed: {err}") from err

            is_retryable: bool = (
                code in (429, 500, 502, 503, 504)
                or "quota" in err_msg
                or "resource_exhausted" in err_msg
            )

            if is_retryable and attempt < MAX_RETRIES:
                logger.warning(
                    f"Transient API error for '{label}' (Attempt "
                    f"{attempt}/{MAX_RETRIES}). Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                return delay * 2.0

            if code == 429 or "quota" in err_msg:
                raise GeminiQuotaError(f"API quota exceeded: {err}") from err

            logger.error(f"Gemini API error for '{label}': {err}")
            raise GeminiAPIError(f"Gemini API failure: {err}") from err

        logger.error(f"Unexpected error calling Gemini API for '{label}': {err}")
        raise GeminiAPIError(f"Unexpected API error: {err}") from err

    def _build_prompt(
        self,
        asset_data: dict[str, Any],
        portfolio_context: dict[str, Any],
    ) -> str:
        """Constructs formatted user prompt payload from input metrics."""
        payload: dict[str, Any] = {
            "asset_info": asset_data,
            "portfolio_context": portfolio_context,
        }
        return json.dumps(payload, indent=2, default=str)

    def _clean_json_text(self, text: str) -> str:
        """Strips markdown code fences from raw LLM text response."""
        cleaned: str = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def _extract_raw_text_safe(self, response: Any) -> str:
        """Safely extracts text from response guarding against safety blocks."""
        try:
            raw_text: str | None = getattr(response, "text", None)
            if raw_text:
                return raw_text
        except Exception as err:
            logger.warning(f"Direct response.text access failed: {err}")

        candidates: list[Any] | None = getattr(response, "candidates", None)
        if candidates and len(candidates) > 0:
            candidate: Any = candidates[0]
            finish_reason: Any = getattr(candidate, "finish_reason", None)
            if finish_reason and str(finish_reason) != "STOP":
                logger.error(f"Gemini generation stopped. Reason: {finish_reason}")
                raise GeminiParsingError(
                    f"Generation blocked (reason: {finish_reason})."
                )

        raise GeminiParsingError("Empty response body from Gemini API.")

    def _log_telemetry(self, ticker: str, start_time: float, response: Any) -> None:
        """Logs execution latency and API token usage metrics."""
        elapsed_ms: float = (time.perf_counter() - start_time) * 1000
        token_info: str = "N/A"

        usage: Any = getattr(response, "usage_metadata", None)
        if usage:
            prompt_tokens: int = getattr(usage, "prompt_token_count", 0)
            candidate_tokens: int = getattr(usage, "candidates_token_count", 0)
            token_info = f"{prompt_tokens} in / {candidate_tokens} out"

        logger.info(
            f"Gemini analysis completed for '{ticker}' | "
            f"Latency: {elapsed_ms:.2f}ms | Tokens: {token_info}"
        )

    def analyze_portfolio_batch(
        self,
        assets_data: list[dict[str, Any]],
        portfolio_context: dict[str, Any],
        model_name: str | None = None,
        temperature: float = 0.1,
    ) -> dict[str, RebalanceRecommendation]:
        """Generates structured rebalancing analysis for all assets in batch.

        Args:
            assets_data: List of enriched target assets.
            portfolio_context: Global portfolio metrics and total value.
            model_name: Optional model override.
            temperature: Output determinism factor.

        Returns:
            Dictionary mapping asset symbols to RebalanceRecommendation.
        """
        if not assets_data:
            raise ValueError("assets_data payload list cannot be empty.")
        if not portfolio_context:
            raise ValueError("portfolio_context payload cannot be empty.")

        target_model: str = model_name or self.model_name
        payload: dict[str, Any] = {
            "target_assets": assets_data,
            "portfolio_context": portfolio_context,
        }
        prompt: str = json.dumps(payload, indent=2, default=str)

        config: types.GenerateContentConfig = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION_BATCH,
            response_mime_type="application/json",
            response_schema=BatchRebalanceRecommendations,
            temperature=temperature,
        )

        asset_count: int = len(assets_data)
        logger.info(
            f"Requesting Gemini batch analysis for {asset_count} assets "
            f"using model '{target_model}'"
        )
        start_time: float = time.perf_counter()

        response: Any = None
        delay: float = INITIAL_RETRY_DELAY

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=target_model,
                    contents=prompt,
                    config=config,
                )
                break
            except Exception as err:
                delay = self._handle_retry_error(err, attempt, "batch", delay)

        elapsed_ms: float = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Gemini batch analysis completed for {asset_count} assets | "
            f"Latency: {elapsed_ms:.2f}ms"
        )

        return self._parse_batch_response(response)

    def _parse_batch_response(
        self, response: Any
    ) -> dict[str, RebalanceRecommendation]:
        """Extracts and validates BatchRebalanceRecommendations from response."""
        batch_obj: BatchRebalanceRecommendations | None = None

        if hasattr(response, "parsed") and response.parsed is not None:
            if isinstance(response.parsed, BatchRebalanceRecommendations):
                batch_obj = response.parsed
            elif isinstance(response.parsed, dict):
                batch_obj = BatchRebalanceRecommendations.model_validate(
                    response.parsed
                )

        if batch_obj is None:
            raw_text: str = self._extract_raw_text_safe(response)
            cleaned_text: str = self._clean_json_text(raw_text)
            try:
                parsed_json: dict[str, Any] = json.loads(cleaned_text)
                batch_obj = BatchRebalanceRecommendations.model_validate(parsed_json)
            except (json.JSONDecodeError, ValidationError) as err:
                logger.error(f"Failed to parse Gemini batch payload: {err}")
                raise GeminiParsingError(
                    f"Structured batch validation failed: {err}"
                ) from err

        return {item.symbol: item.recommendation for item in batch_obj.items}

    def analyze_asset(
        self,
        asset_data: dict[str, Any],
        portfolio_context: dict[str, Any],
        model_name: str | None = None,
        temperature: float = 0.1,
    ) -> RebalanceRecommendation:
        """Generates structured rebalancing analysis for a target asset."""
        self._validate_inputs(asset_data, portfolio_context)

        target_model: str = model_name or self.model_name
        prompt: str = self._build_prompt(
            asset_data=asset_data,
            portfolio_context=portfolio_context,
        )

        config: types.GenerateContentConfig = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=RebalanceRecommendation,
            temperature=temperature,
        )

        ticker: str = str(asset_data.get("symbol", asset_data.get("ticker", "UNKNOWN")))
        logger.info(
            f"Requesting Gemini analysis for asset '{ticker}' "
            f"using model '{target_model}'"
        )
        start_time: float = time.perf_counter()

        response: Any = None
        delay: float = INITIAL_RETRY_DELAY

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=target_model,
                    contents=prompt,
                    config=config,
                )
                break
            except Exception as err:
                delay = self._handle_retry_error(err, attempt, ticker, delay)

        self._log_telemetry(ticker=ticker, start_time=start_time, response=response)
        return self._parse_response(response=response)

    async def analyze_asset_async(
        self,
        asset_data: dict[str, Any],
        portfolio_context: dict[str, Any],
        model_name: str | None = None,
        temperature: float = 0.1,
    ) -> RebalanceRecommendation:
        """Asynchronously generates structured rebalancing analysis."""
        self._validate_inputs(asset_data, portfolio_context)

        target_model: str = model_name or self.model_name
        prompt: str = self._build_prompt(
            asset_data=asset_data,
            portfolio_context=portfolio_context,
        )

        config: types.GenerateContentConfig = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=RebalanceRecommendation,
            temperature=temperature,
        )

        ticker: str = str(asset_data.get("symbol", asset_data.get("ticker", "UNKNOWN")))
        logger.info(
            f"Requesting async Gemini analysis for asset '{ticker}' "
            f"using model '{target_model}'"
        )
        start_time: float = time.perf_counter()

        response: Any = None
        delay: float = INITIAL_RETRY_DELAY

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.aio.models.generate_content(
                    model=target_model,
                    contents=prompt,
                    config=config,
                )
                break
            except APIError as err:
                code: int | None = getattr(err, "code", None)
                err_msg: str = str(err).lower()

                if code in (401, 403) or "auth" in err_msg:
                    logger.error(f"Auth error for '{ticker}': {err}")
                    raise GeminiAuthError(f"Authentication failed: {err}") from err

                is_retryable: bool = (
                    code in (429, 500, 502, 503, 504)
                    or "quota" in err_msg
                    or "resource_exhausted" in err_msg
                )

                if is_retryable and attempt < MAX_RETRIES:
                    logger.warning(
                        f"Transient async API error for '{ticker}' (Attempt "
                        f"{attempt}/{MAX_RETRIES}). Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    delay *= 2.0
                    continue

                if code == 429 or "quota" in err_msg:
                    raise GeminiQuotaError(f"API quota exceeded: {err}") from err

                logger.error(
                    f"Gemini API error during generation for '{ticker}': {err}"
                )
                raise GeminiAPIError(f"Gemini API failure: {err}") from err
            except Exception as err:
                logger.error(
                    f"Unexpected error calling Gemini API for '{ticker}': {err}"
                )
                raise GeminiAPIError(f"Unexpected API error: {err}") from err

        self._log_telemetry(ticker=ticker, start_time=start_time, response=response)
        return self._parse_response(response=response)

    def _parse_response(self, response: Any) -> RebalanceRecommendation:
        """Extracts and validates RebalanceRecommendation from response."""
        if hasattr(response, "parsed") and response.parsed is not None:
            if isinstance(response.parsed, RebalanceRecommendation):
                return response.parsed
            if isinstance(response.parsed, dict):
                return RebalanceRecommendation.model_validate(response.parsed)

        raw_text: str = self._extract_raw_text_safe(response)
        cleaned_text: str = self._clean_json_text(raw_text)

        try:
            parsed_data: dict[str, Any] = json.loads(cleaned_text)
            return RebalanceRecommendation.model_validate(parsed_data)
        except (json.JSONDecodeError, ValidationError) as err:
            logger.error(f"Failed to parse Gemini response payload: {err}")
            raise GeminiParsingError(f"Structured validation failed: {err}") from err
