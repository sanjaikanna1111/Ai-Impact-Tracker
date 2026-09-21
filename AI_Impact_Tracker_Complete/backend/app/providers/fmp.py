"""Optional Financial Modeling Prep enrichment provider.

FMP's stable API is used deliberately: search-symbol, profile and
income-statement.  This module never raises provider failures into research.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("uvicorn.error")


def _normalise(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"\b(limited|ltd|plc|inc|incorporated|corp|corporation|company|co|holdings?)\b", " ", value)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def _similarity(left: str, right: str) -> float:
    left, right = _normalise(left), _normalise(right)
    if not left or not right:
        return 0.0
    return 1.0 if left == right else SequenceMatcher(None, left, right).ratio()


class FMPProvider:
    """Small, conservative async client for FMP structured financial data."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_failure_reason: str | None = None

    @property
    def configured(self) -> bool:
        return bool(settings.fmp_api_key.strip())

    @staticmethod
    def _unavailable(status: str, reason: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"status": status, "provider": "FMP"}
        if reason:
            result["reason"] = reason
        return result

    async def _get(self, path: str, params: dict[str, Any]) -> Any | None:
        if not self.configured:
            return None
        query = {**params, "apikey": settings.fmp_api_key}
        base = settings.fmp_base_url.rstrip("/")
        try:
            if self._client:
                response = await self._client.get(f"{base}/{path.lstrip('/')}", params=query)
            else:
                async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                    response = await client.get(f"{base}/{path.lstrip('/')}", params=query)
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException, httpx.NetworkError) as exc:
            self._last_failure_reason = "network_error"
            logger.warning("[FMP] %s unavailable: %s", path, type(exc).__name__)
            return None
        if response.status_code != 200:
            self._last_failure_reason = {
                401: "invalid_api_key", 403: "forbidden", 404: "not_found",
                429: "rate_limit",
            }.get(response.status_code, "provider_error")
            logger.warning("[FMP] %s unavailable: HTTP %s", path, response.status_code)
            return None
        try:
            return response.json()
        except (ValueError, httpx.DecodingError):
            self._last_failure_reason = "malformed_response"
            logger.warning("[FMP] %s returned malformed JSON", path)
            return None

    async def get_company_profile(self, symbol: str) -> dict[str, Any] | None:
        data = await self._get("profile", {"symbol": symbol})
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return None

    async def get_income_statement(self, symbol: str, period: str = "annual", limit: int = 5) -> list[dict[str, Any]]:
        data = await self._get("income-statement", {"symbol": symbol, "period": period, "limit": limit})
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def _candidate_score(self, requested: str, candidate: dict[str, Any], country: str | None) -> float:
        name = str(candidate.get("name") or candidate.get("companyName") or "")
        score = _similarity(requested, name)
        norm_req = _normalise(requested)
        norm_cand = _normalise(name)
        if norm_req and norm_cand:
            req_words = set(norm_req.split())
            cand_words = set(norm_cand.split())
            if req_words and req_words.issubset(cand_words):
                score = max(score, 0.88)
        requested_country = _normalise(country or "")
        candidate_country = _normalise(str(candidate.get("country") or ""))
        if requested_country and candidate_country:
            score += 0.08 if requested_country in candidate_country or candidate_country in requested_country else -0.12
        exchange = str(candidate.get("exchange") or candidate.get("exchangeShortName") or "")
        if exchange:
            score += 0.02
        return round(max(0.0, min(score, 1.0)), 4)

    async def search_company(self, company_name: str, country: str | None = None) -> dict[str, Any] | None:
        if not self.configured:
            return self._unavailable("not_configured")
        if not company_name.strip():
            return self._unavailable("not_found")
        logger.info("[FMP] Searching company: %s", company_name)
        data = await self._get("search-symbol", {"query": company_name.strip(), "limit": 10})
        if data is None:
            return self._unavailable("temporarily_unavailable", self._last_failure_reason)
        rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
        candidates = []
        for row in rows:
            symbol = row.get("symbol")
            name = row.get("name") or row.get("companyName")
            if not symbol or not name:
                continue
            candidates.append({
                "company_name": name, "symbol": symbol,
                "exchange": row.get("exchange") or row.get("exchangeShortName"),
                "country": row.get("country"), "sector": row.get("sector"),
                "industry": row.get("industry"), "website": row.get("website"),
                "match_confidence": self._candidate_score(company_name, row, country),
            })
        candidates.sort(key=lambda row: row["match_confidence"], reverse=True)
        if not candidates or candidates[0]["match_confidence"] < 0.88:
            logger.info("[FMP] No reliable company match: %s", company_name)
            return self._unavailable("not_found")
        best = candidates[0]
        if len(candidates) > 1 and best["match_confidence"] - candidates[1]["match_confidence"] < 0.04:
            return {"status": "ambiguous", "provider": "FMP", "candidates": candidates[:5]}
        profile = await self.get_company_profile(str(best["symbol"]))
        if profile:
            best.update({key: profile.get(key) or best.get(key) for key in ("country", "sector", "industry", "website")})
            best["company_name"] = profile.get("companyName") or profile.get("name") or best["company_name"]
            best["exchange"] = profile.get("exchangeShortName") or profile.get("exchange") or best["exchange"]
        logger.info("[FMP] Matched company: %s symbol=%s confidence=%.2f", best["company_name"], best["symbol"], best["match_confidence"])
        return {"status": "matched", "provider": "FMP", **best}

    async def get_operating_expenses(self, symbol: str) -> dict[str, Any] | None:
        statements = await self.get_income_statement(symbol, period="annual", limit=5)
        for statement in statements:
            # `operatingExpenses` is the explicit total operating-expense field
            # in FMP stable income-statement responses. Never synthesize it.
            value = statement.get("operatingExpenses")
            if not isinstance(value, (int, float)) or value < 0:
                continue
            fiscal_year = statement.get("calendarYear") or str(statement.get("date") or "")[:4] or None
            return {
                "metric": "Operating expenses", "value": float(value),
                "currency": statement.get("reportedCurrency") or statement.get("currency"),
                "fiscal_year": int(str(fiscal_year)) if str(fiscal_year).isdigit() else fiscal_year,
                "reporting_period": f"FY{fiscal_year}" if fiscal_year else statement.get("period"),
                "source": "Financial Modeling Prep", "provider": "FMP", "symbol": symbol,
                "source_url": f"{settings.fmp_base_url.rstrip('/')}/income-statement?symbol={symbol}&period=annual",
                "source_type": "financial_statement", "retrieved_metric": "operating_expenses",
                "raw_field": "operatingExpenses",
            }
        logger.info("[FMP] Operating expenses unavailable for %s", symbol)
        return None

    async def get_financial_context(self, company_name: str, country: str | None = None) -> dict[str, Any]:
        key = f"{_normalise(company_name)}|{_normalise(country or '')}"
        if key in self._cache:
            logger.info("[FMP] Cache hit: %s", company_name)
            return self._cache[key]
        match = await self.search_company(company_name, country)
        if not match or match.get("status") != "matched":
            result = match or self._unavailable("temporarily_unavailable")
            self._cache[key] = result
            return result
        symbol = str(match["symbol"])
        operating_expenses = await self.get_operating_expenses(symbol)
        statement = (await self.get_income_statement(symbol, period="annual", limit=1))
        latest = statement[0] if statement else {}
        metrics = [operating_expenses] if operating_expenses else []
        for field, label in (("revenue", "Revenue"), ("operatingIncome", "Operating income"), ("costOfRevenue", "Cost of revenue"), ("sellingGeneralAndAdministrativeExpenses", "Selling, general and administrative expense"), ("researchAndDevelopmentExpenses", "Research and development expense")):
            value = latest.get(field)
            if isinstance(value, (int, float)):
                metrics.append({"metric": label, "value": float(value), "currency": latest.get("reportedCurrency") or latest.get("currency"), "fiscal_year": latest.get("calendarYear"), "reporting_period": f"FY{latest.get('calendarYear')}" if latest.get("calendarYear") else latest.get("period"), "source": "Financial Modeling Prep", "provider": "FMP", "symbol": symbol, "source_type": "financial_statement", "retrieved_metric": field, "raw_field": field, "source_url": f"{settings.fmp_base_url.rstrip('/')}/income-statement?symbol={symbol}&period=annual"})
        result = {"status": "available", "provider": "FMP", "identity": match, "symbol": symbol, "company_name": match["company_name"], "metrics": metrics, "operating_expenses": operating_expenses.get("value") if operating_expenses else None, "currency": operating_expenses.get("currency") if operating_expenses else latest.get("reportedCurrency"), "fiscal_year": operating_expenses.get("fiscal_year") if operating_expenses else latest.get("calendarYear")}
        self._cache[key] = result
        return result
