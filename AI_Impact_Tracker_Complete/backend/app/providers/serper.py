import asyncio
import time
import logging
import re
import httpx
from urllib.parse import urlsplit
from app.config import settings
from app.schemas import SearchResult

logger = logging.getLogger("uvicorn.error")


class SerperProvider:
    BASE = 'https://google.serper.dev'

    def __init__(self):
        # Serper's free/low tiers can reject bursts. Keep starts deliberately spaced
        # and retry 429/5xx responses rather than silently losing evidence.
        self._semaphore = asyncio.Semaphore(2)
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._min_interval_seconds = 0.85

    async def _throttle(self):
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_at
            wait_for = self._min_interval_seconds - elapsed
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_request_at = time.monotonic()

    @staticmethod
    def normalize_search_query(query: str, maximum_length: int = 500) -> str:
        """Make generated queries safe without losing useful site: constraints."""
        query = re.sub(r"[\x00-\x1f\x7f]+", " ", str(query or ""))
        query = re.sub(r"\s+", " ", query).strip()
        seen: set[str] = set()
        def unique_quoted(match: re.Match[str]) -> str:
            token = re.sub(r"\s+", " ", match.group(1)).strip()
            key = token.casefold()
            if key in seen:
                return ""
            seen.add(key)
            return f'"{token}"'
        query = re.sub(r'"([^"]+)"', unique_quoted, query)
        return re.sub(r"\s+", " ", query).strip()[:maximum_length].strip()

    async def search(self, query: str, num: int = 10, search_type: str = 'search') -> list[SearchResult]:
        if not settings.serper_api_key:
            return []
        query = self.normalize_search_query(query)
        if not query:
            return []

        endpoint = 'news' if search_type == 'news' else 'search'
        headers = {
            'X-API-KEY': settings.serper_api_key,
            'Content-Type': 'application/json',
        }

        async with self._semaphore:
            async with httpx.AsyncClient(timeout=35) as client:
                last_error = None
                for attempt in range(5):
                    await self._throttle()
                    try:
                        r = await client.post(
                            f'{self.BASE}/{endpoint}',
                            headers=headers,
                            json={'q': query, 'num': min(max(int(num), 1), 10)},
                        )

                        if r.status_code == 429:
                            retry_after = r.headers.get('Retry-After')
                            try:
                                wait_for = float(retry_after) if retry_after else (1.5 * (2 ** attempt))
                            except ValueError:
                                wait_for = 1.5 * (2 ** attempt)
                            await asyncio.sleep(min(wait_for, 20))
                            continue

                        if 500 <= r.status_code < 600:
                            await asyncio.sleep(min(1.25 * (2 ** attempt), 12))
                            continue

                        if r.status_code >= 400:
                            logger.warning("[SERPER] status=%s query=%s response_body=%s", r.status_code, query, r.text[:1200])

                        r.raise_for_status()
                        data = r.json()
                        rows = data.get('organic', []) if endpoint == 'search' else data.get('news', [])
                        return [
                            SearchResult(
                                title=x.get('title', ''),
                                url=x.get('link', ''),
                                snippet=x.get('snippet', ''),
                                position=x.get('position', i + 1),
                                search_provider='serper',
                                domain=(urlsplit(x.get('link', '')).hostname or '').lower().removeprefix('www.'),
                                query=query,
                            )
                            for i, x in enumerate(rows)
                            if x.get('link')
                        ]
                    except (httpx.HTTPError, ValueError) as exc:
                        last_error = exc
                        if attempt < 4:
                            await asyncio.sleep(min(1.25 * (2 ** attempt), 12))
                            continue
                        raise

                if last_error:
                    raise last_error
                return []
