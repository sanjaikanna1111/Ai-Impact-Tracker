import logging
import re
from html.parser import HTMLParser
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self.title: str = ""
        self._in_title: bool = False
        self._ignore: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "noscript", "svg", "head"):
            self._ignore = True
        elif tag_lower == "title":
            self._in_title = True
        elif tag_lower in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.text.append("\n")

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "noscript", "svg", "head"):
            self._ignore = False
        elif tag_lower == "title":
            self._in_title = False
        elif tag_lower in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.text.append("\n")

    def handle_data(self, data: str):
        if self._in_title:
            self.title += data
        elif not self._ignore:
            self.text.append(data)


def _html_to_text(html_content: str) -> tuple[str, str]:
    """Extract page title and clean text from raw HTML without third-party dependencies."""
    try:
        parser = _HTMLTextExtractor()
        parser.feed(html_content)
        raw = "".join(parser.text)
        clean = re.sub(r"[ \t]+", " ", raw)
        clean = re.sub(r"\n\s*\n+", "\n\n", clean).strip()
        return parser.title.strip(), clean
    except Exception as exc:
        logger.debug("[JINA] HTML parsing error: %s", exc)
        clean = re.sub(r"<[^>]+>", " ", html_content)
        clean = re.sub(r"\s+", " ", clean).strip()
        return "", clean


class JinaProvider:
    """Document reader combining Jina Reader API with transparent direct HTTP fallback."""

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    async def _direct_read(self, url: str) -> dict:
        """Fetch and extract text directly via HTTP when Jina is unavailable/exhausted."""
        headers = {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    content_type = r.headers.get("content-type", "").lower()
                    if "html" in content_type:
                        title, text = _html_to_text(r.text)
                        return {
                            "url": url,
                            "final_url": str(r.url),
                            "title": title,
                            "content": text[:40000],
                            "published_at": None,
                            "reader": "direct_http",
                        }
                    else:
                        return {
                            "url": url,
                            "final_url": str(r.url),
                            "title": "",
                            "content": r.text[:40000],
                            "published_at": None,
                            "reader": "direct_http",
                        }
                logger.debug("[JINA] Direct read status %s for %s", r.status_code, url)
        except Exception as exc:
            logger.debug("[JINA] Direct read failed for %s: %s", url, exc)
        return {"url": url, "title": "", "content": "", "published_at": None, "reader": "failed"}

    async def read(self, url: str) -> dict:
        if not url:
            return {"url": "", "title": "", "content": "", "published_at": None}

        # If Jina API key is absent, use direct read immediately
        if not settings.jina_api_key.strip():
            return await self._direct_read(url)

        headers = {"Accept": "application/json", "X-Return-Format": "markdown"}
        headers["Authorization"] = f"Bearer {settings.jina_api_key}"
        target = f"https://r.jina.ai/{url}"

        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(target, headers=headers)
                if r.status_code == 200:
                    try:
                        payload = r.json()
                        data = payload.get("data", payload)
                        return {
                            "url": url,
                            "title": data.get("title", ""),
                            "content": data.get("content", ""),
                            "published_at": data.get("publishedTime"),
                            "reader": "jina",
                        }
                    except Exception:
                        return {
                            "url": url,
                            "title": "",
                            "content": r.text,
                            "published_at": None,
                            "reader": "jina_raw",
                        }
                else:
                    logger.info(
                        "[JINA] Jina returned HTTP %s for %s, falling back to direct fetch",
                        r.status_code,
                        url,
                    )
        except Exception as exc:
            logger.info(
                "[JINA] Jina request failed for %s (%s), falling back to direct fetch",
                url,
                type(exc).__name__,
            )

        # Automatic graceful fallback to direct HTTP reading
        return await self._direct_read(url)
