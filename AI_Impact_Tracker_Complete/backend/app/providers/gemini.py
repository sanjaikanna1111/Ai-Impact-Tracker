from typing import Any, TypeVar

import asyncio
import random
import json
import logging
import time
import re
from email.utils import parsedate_to_datetime

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.config import settings


T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("uvicorn.error")


class GeminiUnavailableError(RuntimeError):
    """Expected provider condition: the caller must use its deterministic fallback."""


class GeminiProvider:
    def __init__(self):
        self.clients = []

        if settings.gemini_api_key:
            self.clients.append(
                genai.Client(
                    api_key=settings.gemini_api_key
                )
            )

        if settings.gemini_key_fallback:
            fallback = (
                settings.gemini_key_fallback.strip()
            )

            if (
                fallback
                and fallback
                != settings.gemini_api_key
            ):
                self.clients.append(
                    genai.Client(
                        api_key=fallback
                    )
                )

        # The credential that most recently succeeded
        # is tried first on the next request.
        self._preferred_client_index = 0
        # A provider belongs to one ResearchService instance, so this state is
        # naturally scoped to one research run rather than persisted globally.
        self._key_health = ["AVAILABLE" for _ in self.clients]

    # ========================================================
    # ERROR CLASSIFICATION
    # ========================================================

    @staticmethod
    def _is_truncated_json_error(
        error: Exception,
    ) -> bool:
        """
        Detect structured-output failures caused by
        incomplete/truncated Gemini JSON.

        These are worth retrying because the model may
        successfully complete the same structured response
        on another request.
        """

        if not isinstance(
            error,
            ValidationError,
        ):
            return False

        message = str(
            error
        ).lower()

        truncated_patterns = (
            "eof while parsing",
            "unexpected eof",
            "unexpected end",
            "end of input",
            "unterminated string",
            "unterminated",
            "json_eof",
            "invalid json: eof",
        )

        return any(
            pattern in message
            for pattern in truncated_patterns
        )

    @staticmethod
    def _is_retryable_error(
        error: Exception,
    ) -> bool:
        """
        Retry temporary service/network failures.

        Ordinary schema-validation failures are not
        retryable here.

        Truncated structured JSON is handled separately.
        """

        if isinstance(
            error,
            ValidationError,
        ):
            return False

        # asyncio.wait_for raises asyncio.TimeoutError (an alias of the
        # built-in TimeoutError on supported Python versions).  Its message is
        # commonly empty, so string matching alone incorrectly marked it as a
        # permanent failure.
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return True

        if isinstance(
            error,
            (
                httpx.TransportError,
                httpx.TimeoutException,
            ),
        ):
            return True

        error_name = (
            type(error).__name__.lower()
        )

        message = (
            str(error).lower()
        )

        retryable_error_names = {
            "readerror",
            "connecterror",
            "connecttimeout",
            "readtimeout",
            "writetimeout",
            "pooltimeout",
            "remoteprotocolerror",
            "networkerror",
            "servererror",
        }

        if (
            error_name
            in retryable_error_names
        ):
            return True

        retryable_patterns = (
            "429",
            "resource_exhausted",
            "rate limit",
            "rate_limit",
            "500",
            "502",
            "503",
            "504",
            "unavailable",
            "high demand",
            "service unavailable",
            "temporarily unavailable",
            "internal server error",
            "deadline exceeded",
            "timed out",
            "timeout",
            "connection reset",
            "connection aborted",
            "connection closed",
            "server disconnected",
            "remote protocol",
            "read error",
            "readerror",
            "empty response",
        )

        return any(
            pattern in message
            for pattern in retryable_patterns
        )

    @staticmethod
    def _is_quota_error(
        error: Exception,
    ) -> bool:
        """
        Quota/rate-limit errors should move to the next
        configured credential without repeatedly hammering
        the same credential.
        """

        message = (
            str(error).lower()
        )

        quota_patterns = (
            "429",
            "resource_exhausted",
            "quota exceeded",
            "quota",
            "rate limit",
            "rate_limit",
            "generaterequestsperdayperprojectpermodel",
            "free_tier_requests",
        )

        return any(
            pattern in message
            for pattern in quota_patterns
        )

    @staticmethod
    def _is_daily_quota_error(error: Exception) -> bool:
        message = str(error).lower()
        return any(
            pattern in message
            for pattern in (
                "generaterequestsperdayperprojectpermodel",
                "requestsperday",
                "daily quota",
                "per day",
            )
        )

    @staticmethod
    def _is_minute_rate_limit(error: Exception) -> bool:
        message = str(error).lower()
        return (
            "429" in message
            or "resource_exhausted" in message
            or "rate limit" in message
        ) and not GeminiProvider._is_daily_quota_error(error)

    @staticmethod
    def _is_credential_error(error: Exception) -> bool:
        """Errors for which retrying the same credential is pointless."""
        message = str(error).lower()
        return any(
            pattern in message
            for pattern in (
                "401",
                "403",
                "unauthorized",
                "forbidden",
                "invalid api key",
                "invalid credential",
                "permission denied",
            )
        )

    @staticmethod
    def _retry_delay(error: Exception, attempt: int) -> float:
        """Use a reasonable provider Retry-After value, else short jittered backoff."""
        retry_after = None
        for candidate in (error, getattr(error, "response", None)):
            headers = getattr(candidate, "headers", None)
            if headers is None:
                headers = getattr(candidate, "response_headers", None)
            if headers:
                try:
                    retry_after = headers.get("Retry-After") or headers.get("retry-after")
                except AttributeError:
                    pass
            if retry_after:
                break

        if retry_after:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                try:
                    delay = parsedate_to_datetime(str(retry_after)).timestamp() - time.time()
                except (TypeError, ValueError, IndexError, OverflowError):
                    delay = 0.0
            if delay > 0:
                return min(delay, 15.0)

        # Three total attempts: waits after attempts one and two are ~2s and ~5s.
        base_delay = 2.0 if attempt == 1 else 5.0
        return base_delay + random.uniform(0.0, 0.5)

    @staticmethod
    def _provider_rate_limit_delay(error: Exception) -> float | None:
        """Return Gemini's retry delay plus a small buffer when it is safe to wait."""
        message = str(error)
        retry_after = None
        for candidate in (error, getattr(error, "response", None)):
            headers = getattr(candidate, "headers", None) or getattr(candidate, "response_headers", None)
            if headers:
                try:
                    retry_after = headers.get("Retry-After") or headers.get("retry-after")
                except AttributeError:
                    pass
            if retry_after:
                break

        delay = None
        if retry_after:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                try:
                    delay = parsedate_to_datetime(str(retry_after)).timestamp() - time.time()
                except (TypeError, ValueError, IndexError, OverflowError):
                    delay = None

        if delay is None:
            match = re.search(
                r"(?:retry[_ ]?delay|please retry in)\s*[:=]?\s*['\"]?(\d+(?:\.\d+)?)\s*s",
                message,
                re.IGNORECASE,
            )
            if match:
                delay = float(match.group(1))

        if delay is None or delay <= 0:
            return None

        buffered = delay + 1.0
        maximum = max(1.0, float(settings.gemini_rate_limit_max_wait_seconds))
        return buffered if buffered <= maximum else None

    # ========================================================
    # CLIENT ORDER
    # ========================================================

    def _client_order(
        self,
    ) -> list[int]:
        count = len(
            self.clients
        )

        if count == 0:
            return []

        if count == 1:
            return [0]

        preferred = (
            self._preferred_client_index
            if (
                0
                <= self._preferred_client_index
                < count
            )
            else 0
        )

        return [
            (
                preferred
                + offset
            )
            % count
            for offset
            in range(count)
        ]

    # ========================================================
    # SINGLE REQUEST
    # ========================================================

    @staticmethod
    def _sanitize_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
        """Inline Pydantic references and remove response-schema keywords Gemini rejects."""
        definitions = schema.get("$defs", {})
        unsupported = {"$defs", "$schema", "title", "examples", "default", "maxItems", "minItems", "exclusiveMinimum", "exclusiveMaximum", "pattern", "format", "additionalProperties"}

        def clean(value: Any) -> Any:
            if isinstance(value, list):
                return [clean(item) for item in value]
            if not isinstance(value, dict):
                return value
            if "$ref" in value:
                ref = value["$ref"].rsplit("/", 1)[-1]
                return clean(definitions.get(ref, {}))
            result: dict[str, Any] = {}
            nullable = False
            for key, item in value.items():
                if key in unsupported:
                    continue
                if key == "anyOf" and isinstance(item, list):
                    non_null = [part for part in item if not (isinstance(part, dict) and part.get("type") == "null")]
                    if len(non_null) == 1 and len(non_null) != len(item):
                        result.update(clean(non_null[0]))
                        nullable = True
                    else:
                        result[key] = clean(item)
                    continue
                result[key] = clean(item)
            if nullable:
                result["nullable"] = True
            return result

        return clean(schema)

    @classmethod
    def _response_schema(cls, schema: type[T]) -> dict[str, Any]:
        return cls._sanitize_schema_for_gemini(schema.model_json_schema())

    @staticmethod
    def _safe_schema_diagnostics(prompt: str, schema: type[T], response_schema: dict[str, Any]) -> None:
        logger.warning(
            "[GEMINI] INVALID_ARGUMENT schema=%s prompt_chars=%s top_fields=%s config=%s schema=%s",
            schema.__name__, len(prompt), list(response_schema.get("properties", {}).keys()),
            {"temperature": 0.1, "response_mime_type": "application/json"},
            json.dumps(response_schema, ensure_ascii=True)[:12000],
        )

    async def _generate_with_client(
        self,
        client,
        prompt: str,
        schema: type[T],
    ) -> T:
        """
        Execute one Gemini structured-output request.
        """

        response_schema = self._response_schema(schema)
        started = time.monotonic()
        timeout = max(1.0, float(settings.gemini_timeout_seconds))
        logger.info("[GEMINI] request started model=%s timeout=%.0fs", settings.gemini_model, timeout)
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        # No tools or function declarations are passed by this app.
                        response_schema=schema,
                    ),
                ),
                timeout=timeout,
            )
        except Exception as exc:
            logger.info("[GEMINI] request failed in %.2fs (%s)", time.monotonic() - started, type(exc).__name__)
            if "400" in str(exc) and "invalid_argument" in str(exc).lower():
                self._safe_schema_diagnostics(prompt, schema, response_schema)
            raise

        logger.info("[GEMINI] request completed in %.2fs", time.monotonic() - started)

        if not response.text:
            raise RuntimeError(
                "Gemini returned an empty response."
            )

        return schema.model_validate_json(
            response.text
        )

    # ========================================================
    # STRUCTURED OUTPUT WITH RETRIES
    # ========================================================

    async def structured(
        self,
        prompt: str,
        schema: type[T],
    ) -> T:
        """
        Generate validated structured output.

        Behaviour:

        503/network/temporary errors
            -> retry same credential

        truncated JSON / EOF
            -> retry same credential

        per-minute rate limit
            -> wait for Gemini's stated retry delay when reasonably bounded

        daily quota exhaustion
            -> disable that credential for this research run and move on

        genuine schema mismatch
            -> raise immediately

        successful credential
            -> becomes preferred credential
        """

        if not self.clients:
            raise RuntimeError(
                "No Gemini API key is configured."
            )

        # Tests and embedding callers may replace ``clients`` after provider
        # construction.  Keep the run-scoped health bookkeeping aligned rather
        # than converting that safe substitution into an IndexError.
        if len(self._key_health) != len(self.clients):
            self._key_health = ["AVAILABLE" for _ in self.clients]

        order = [
            index for index in self._client_order()
            if self._key_health[index] == "AVAILABLE"
        ]

        if not order:
            print("[GEMINI] No usable credentials for current run; skipping Gemini call.", flush=True)
            raise GeminiUnavailableError("No usable Gemini credentials remain for this research run.")

        last_error: Exception | None = (
            None
        )

        # Keep temporary failures bounded.  This is deliberately per credential:
        # only after three transient attempts do we try the fallback key.
        max_attempts_per_key = 3

        for (
            order_position,
            client_index,
        ) in enumerate(
            order
        ):
            client = (
                self.clients[
                    client_index
                ]
            )

            for attempt in range(
                1,
                max_attempts_per_key + 1,
            ):
                try:
                    print(
                        (
                            f"[GEMINI] Using key "
                            f"{client_index + 1}/"
                            f"{len(self.clients)} "
                            f"(attempt {attempt}/"
                            f"{max_attempts_per_key})"
                        ),
                        flush=True,
                    )

                    result = (
                        await self._generate_with_client(
                            client,
                            prompt,
                            schema,
                        )
                    )

                    self._preferred_client_index = (
                        client_index
                    )

                    print(
                        (
                            f"[GEMINI] Key "
                            f"{client_index + 1} "
                            "succeeded"
                        ),
                        flush=True,
                    )

                    return result

                # ============================================
                # STRUCTURED OUTPUT VALIDATION
                # ============================================

                except ValidationError as error:
                    last_error = error

                    # ----------------------------------------
                    # TRUNCATED / INCOMPLETE JSON
                    # ----------------------------------------

                    if self._is_truncated_json_error(
                        error
                    ):
                        print(
                            (
                                "[GEMINI] Structured JSON "
                                "was truncated/incomplete."
                            ),
                            flush=True,
                        )

                        if (
                            attempt
                            < max_attempts_per_key
                        ):
                            delay = self._retry_delay(error, attempt)

                            print(
                                (
                                    "[GEMINI] Retrying "
                                    f"key {client_index + 1} "
                                    f"in {delay:.1f}s..."
                                ),
                                flush=True,
                            )

                            await asyncio.sleep(
                                delay
                            )

                            continue

                        print(
                            (
                                f"[GEMINI] Key "
                                f"{client_index + 1} "
                                "repeatedly returned "
                                "truncated JSON."
                            ),
                            flush=True,
                        )

                        break

                    # ----------------------------------------
                    # REAL SCHEMA VALIDATION FAILURE
                    # ----------------------------------------

                    print(
                        (
                            "[GEMINI] Structured-output "
                            "schema validation failed. "
                            "Not retrying because this "
                            "does not appear to be "
                            "truncated JSON."
                        ),
                        flush=True,
                    )

                    raise

                # ============================================
                # OTHER GEMINI / NETWORK ERRORS
                # ============================================

                except Exception as error:
                    last_error = error

                    # Do not stringify provider exceptions: SDK/network
                    # errors can include request metadata, and credentials
                    # must never reach logs.  The type and attempt identify
                    # the actionable failure safely.
                    logger.warning(
                        "[GEMINI] provider=gemini model=%s key_index=%s attempt=%s/%s error_type=%s",
                        settings.gemini_model,
                        client_index + 1,
                        attempt,
                        max_attempts_per_key,
                        type(error).__name__,
                    )

                    # ----------------------------------------
                    # INVALID CREDENTIAL / ACCESS
                    # ----------------------------------------

                    if self._is_credential_error(
                        error
                    ):
                        self._key_health[client_index] = "INVALID"
                        print(
                            (
                                "[GEMINI] Credential/access "
                                "failure. Moving to the next "
                                "configured credential."
                            ),
                            flush=True,
                        )

                        break

                    # ----------------------------------------
                    # DAILY QUOTA: do not spend further requests on this key
                    # ----------------------------------------

                    if self._is_daily_quota_error(error):
                        self._key_health[client_index] = "DAILY_QUOTA_EXHAUSTED"
                        print(
                            f"[GEMINI] 429 daily quota exhausted; key {client_index + 1} disabled for current research run.",
                            flush=True,
                        )
                        break

                    # ----------------------------------------
                    # PER-MINUTE RATE LIMIT: Gemini, not generic backoff,
                    # determines whether a same-key retry is appropriate.
                    # ----------------------------------------

                    if self._is_minute_rate_limit(error):
                        self._key_health[client_index] = "TEMPORARILY_RATE_LIMITED"
                        delay = self._provider_rate_limit_delay(error)
                        if attempt < max_attempts_per_key and delay is not None:
                            print(
                                f"[GEMINI] 429 per-minute rate limit; provider retry delay={delay - 1:.1f}s; key temporarily rate limited; retrying in {delay:.1f}s.",
                                flush=True,
                            )
                            await asyncio.sleep(delay)
                            self._key_health[client_index] = "AVAILABLE"
                            continue

                        self._key_health[client_index] = "AVAILABLE"
                        print(
                            f"[GEMINI] 429 rate limit has no reasonable provider delay; rotating from key {client_index + 1}.",
                            flush=True,
                        )
                        break

                    # ----------------------------------------
                    # PERMANENT FAILURE
                    # ----------------------------------------

                    if not self._is_retryable_error(
                        error
                    ):
                        print(
                            (
                                "[GEMINI] Failure is not "
                                "transient. Not retrying."
                            ),
                            flush=True,
                        )

                        raise

                    # ----------------------------------------
                    # TRANSIENT FAILURE
                    # ----------------------------------------

                    if (
                        attempt
                        < max_attempts_per_key
                    ):
                        delay = self._retry_delay(error, attempt)

                        print(
                            (
                                f"[GEMINI] {'Rate-limit' if self._is_quota_error(error) else 'Transient'} "
                                f"failure ({type(error).__name__}); "
                                f"retrying key "
                                f"{client_index + 1} "
                                f"in {delay:.1f}s..."
                            ),
                            flush=True,
                        )

                        await asyncio.sleep(
                            delay
                        )

                        continue

                    print(
                        (
                            f"[GEMINI] Key "
                            f"{client_index + 1} "
                            f"exhausted {'rate-limit' if self._is_quota_error(error) else 'transient'} retries."
                        ),
                        flush=True,
                    )

                    break

            # ================================================
            # MOVE TO NEXT CREDENTIAL
            # ================================================

            remaining_credentials = (
                len(order)
                - order_position
                - 1
            )

            if (
                remaining_credentials
                > 0
            ):
                next_client_index = (
                    order[
                        order_position
                        + 1
                    ]
                )

                self._preferred_client_index = (
                    next_client_index
                )

                print(
                    (
                        "[GEMINI] Trying fallback key "
                        f"{next_client_index + 1}/"
                        f"{len(self.clients)}..."
                    ),
                    flush=True,
                )

        print("[GEMINI] All configured credentials unavailable; continuing with deterministic fallback.", flush=True)
        raise GeminiUnavailableError(
            (
                "All configured Gemini API credentials "
                "failed after retries. "
                f"Last error type: {type(last_error).__name__ if last_error else 'unknown'}"
            )
        )
