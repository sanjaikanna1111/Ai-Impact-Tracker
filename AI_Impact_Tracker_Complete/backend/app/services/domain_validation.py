from urllib.parse import urlparse
import tldextract  # type: ignore[import-not-found] # pyright: ignore[reportMissingImports]

BLOCKED = {
    'g2.com','capterra.com','trustpilot.com','reddit.com','gartner.com','getapp.com','softwareadvice.com',
    'youtube.com','wikipedia.org','linkedin.com','crunchbase.com','marketsandmarkets.com','emergenresearch.com',
    'globenewswire.com','prnewswire.com'
}

def registrable(url: str) -> str:
    e = tldextract.extract(url)
    return '.'.join(x for x in [e.domain,e.suffix] if x)

def is_vendor_candidate(url: str) -> bool:
    d = registrable(url).lower()
    return bool(d) and not any(d == x or d.endswith('.'+x) for x in BLOCKED)

def same_domain(a: str, b: str) -> bool:
    return registrable(a).lower() == registrable(b).lower()
