"""Optional Microsoft Foundry Grounding with Bing Search discovery provider.

This deliberately calls the current Foundry Responses API and its
``bing_grounding`` tool.  It does not call the retired Bing Web Search v7 API.
Foundry returns model output plus URL-citation annotations rather than raw Bing
results, so only those publisher URLs are returned to the research pipeline.
"""

import logging
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.schemas import SearchResult

logger = logging.getLogger("uvicorn.error")


class BingGroundingProvider:
    """Fail-open Foundry Bing-grounded source discovery."""

    @property
    def configured(self) -> bool:
        return bool(
            settings.bing_web_search_enabled
            and settings.azure_foundry_project_endpoint
            and settings.azure_foundry_bearer_token
            and settings.azure_foundry_model_deployment
            and settings.bing_project_connection_id
        )

    @staticmethod
    def _domain(url: str) -> str:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")

    async def search(self, query: str, num: int = 8) -> list[SearchResult]:
        """Return only publisher URLs provided in Foundry URL citations.

        Bing grounding is evidence *discovery*.  Its generated answer is kept
        only as a short snippet; downstream Jina extraction and entity checks
        determine whether the cited publisher page proves anything.
        """
        if not self.configured or not query.strip():
            return []

        endpoint = settings.azure_foundry_project_endpoint.rstrip("/")
        payload = {
            "model": settings.azure_foundry_model_deployment,
            "input": (
                "Use Bing grounding for this exact web-evidence discovery query: "
                f"{query}\nReturn a concise factual overview and cite every "
                "publisher page used. Do not invent URLs or claim adoption."
            ),
            "tool_choice": "required",
            "tools": [{
                "type": "bing_grounding",
                "bing_grounding": {"search_configurations": [{
                    "project_connection_id": settings.bing_project_connection_id,
                    "count": min(max(int(num), 1), 50),
                    "market": settings.bing_search_market,
                    "set_lang": settings.bing_search_language,
                }]},
            }],
        }
        headers = {
            "Authorization": f"Bearer {settings.azure_foundry_bearer_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(f"{endpoint}/openai/v1/responses", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Optional provider failures must never affect /api/research.
            logger.warning("[CUSTOMER SEARCH] Bing grounding unavailable: %s", exc)
            return []

        results: list[SearchResult] = []
        seen: set[str] = set()
        position = 0
        for item in data.get("output", []):
            for content in item.get("content", []) if isinstance(item, dict) else []:
                if content.get("type") != "output_text":
                    continue
                snippet = str(content.get("text") or "")[:1000]
                for annotation in content.get("annotations") or []:
                    if annotation.get("type") != "url_citation":
                        continue
                    url = str(annotation.get("url") or "").strip()
                    canonical = url.rstrip("/").lower()
                    if not url or canonical in seen:
                        continue
                    seen.add(canonical)
                    position += 1
                    results.append(SearchResult(
                        title=str(annotation.get("title") or self._domain(url) or "Bing-grounded source"),
                        url=url,
                        domain=self._domain(url),
                        snippet=snippet,
                        position=position,
                        search_provider="bing",
                        query=query,
                    ))
        return results
