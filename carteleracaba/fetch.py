"""HTTP helper: solo stdlib (urllib), con User-Agent de navegador,
reintentos con backoff, timeout y cache opcional en disco.

Sin dependencias externas -> el cron corre con cualquier python3.
"""
from __future__ import annotations

import gzip
import io
import os
import ssl
import time
import urllib.error
import urllib.request

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class FetchError(RuntimeError):
    pass


def get(
    url: str,
    *,
    timeout: int = 25,
    retries: int = 3,
    backoff: float = 2.0,
    insecure: bool = False,
) -> str:
    """GET con reintentos. Devuelve el body como texto utf-8.

    insecure=True desactiva verificación TLS (algunos cines tienen
    el certificado vencido, p.ej. cinegaumont.ar).
    """
    ctx = None
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml,application/json,*/*",
                "Accept-Language": "es-AR,es;q=0.9",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                return raw.decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ssl.SSLError) as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(backoff ** attempt)
    raise FetchError(f"GET fallo tras {retries} intentos: {url} ({last_err})")


def get_cached(url: str, cache_path: str, *, max_age_s: int = 0, **kw) -> str:
    """Como get(), pero guarda/lee de cache_path. max_age_s=0 => sin reuso
    (siempre baja fresco; cache queda como raw del run para debug)."""
    if max_age_s and os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < max_age_s:
            with open(cache_path, "r", encoding="utf-8") as fh:
                return fh.read()
    body = get(url, **kw)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return body
