"""Fuente: Comunidad Cinéfila (comunidadcinefila.org) — sitio Wix Events.

Hace ciclos itinerantes de cine en CABA: Yunta Bar (bar de Radio
Futurock, Lavalle 3491), Bargoglio y su propia sede. La data de Wix
Events se carga por API en runtime y NO esta en el HTML, PERO:

  - /sitemap.xml -> /event-pages-sitemap.xml lista cada evento
  - cada /event-details/<slug> trae JSON-LD <@type Event> con
    name, startDate, endDate, location(name+address), eventStatus

Asi detectamos automaticamente funciones nuevas (incl. Yunta) sin
reverse-engineering de la API privada de Wix.

scrape() devuelve resultados con el mismo shape que
cartelera_ar.scrape_cinema(): [{cinema, movies, functions}, ...]
agrupados por sede (yunta-bar o comunidad-cinefila).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from .fetch import get

SITEMAP = "https://www.comunidadcinefila.org/sitemap.xml"
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_LDJSON_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.S
)

# pistas de que NO es CABA (descartar)
_NON_CABA = (
    "provincia de buenos aires",
    "la plata",
    "mar del plata",
    "rosario",
    "cordoba",
    "córdoba",
    "mendoza",
    "tucuman",
    "tucumán",
)
# pistas de Yunta Bar
_YUNTA = ("yunta", "lavalle 3491", "lavalle 3,491")

CINEMAS = {
    "yunta-bar": {
        "slug": "yunta-bar",
        "name": "Yunta Bar (Comunidad Cinéfila)",
        "chain": "Bar-cine",
        "street": "Lavalle 3491",
        "locality": "Almagro",
        "region": "CABA",
        "phone": None,
        "lat": -34.6033,
        "lng": -58.4181,
        "official_url": "https://www.comunidadcinefila.org/comunidadcinefilaenyunta",
        "cartelera_url": "https://www.comunidadcinefila.org/comunidadcinefilaenyunta",
        "url": "https://www.comunidadcinefila.org/comunidadcinefilaenyunta",
        "source_url": "https://www.comunidadcinefila.org/comunidadcinefilaenyunta",
    },
    "comunidad-cinefila": {
        "slug": "comunidad-cinefila",
        "name": "Comunidad Cinéfila (itinerante)",
        "chain": "Cineclub",
        "street": "Sedes varias (CABA)",
        "locality": "CABA",
        "region": "CABA",
        "phone": None,
        "lat": None,
        "lng": None,
        "official_url": "https://www.comunidadcinefila.org",
        "cartelera_url": "https://www.comunidadcinefila.org",
        "url": "https://www.comunidadcinefila.org",
        "source_url": "https://www.comunidadcinefila.org",
    },
}


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:80]


def _event_urls() -> list[str]:
    """Lee sitemap -> event-pages-sitemap.xml -> URLs de eventos."""
    root = get(SITEMAP)
    sub = [u for u in _LOC_RE.findall(root) if "event-pages-sitemap" in u]
    urls: list[str] = []
    for sm in sub:
        urls += [
            u for u in _LOC_RE.findall(get(sm)) if "/event-details/" in u
        ]
    return sorted(set(urls))


def _parse_event(url: str) -> dict | None:
    html = get(url)
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for it in data if isinstance(data, list) else [data]:
            t = it.get("@type")
            if t in ("Event", "ScreeningEvent", "BusinessEvent", "TheaterEvent"):
                return it
    return None


def scrape(*, on_progress=None) -> list[dict]:
    try:
        urls = _event_urls()
    except Exception as exc:
        if on_progress:
            on_progress("sitemap", False, f"error: {exc}")
        return []

    today = date.today().isoformat()
    # acumular por sede
    buckets: dict[str, dict] = {}

    for url in urls:
        try:
            ev = _parse_event(url)
        except Exception as exc:
            if on_progress:
                on_progress(url.split("/")[-1], False, f"error: {exc}")
            continue
        if not ev:
            continue

        start = ev.get("startDate")
        name = (ev.get("name") or "").strip()
        if not (start and name):
            continue

        try:
            dt = datetime.fromisoformat(start)
            d_s = dt.date().isoformat()
            t_s = dt.strftime("%H:%M")
        except ValueError:
            d_s, t_s = start[:10], start[11:16]

        if d_s < today:  # solo funciones futuras
            continue

        loc = ev.get("location") or {}
        loc_name = loc.get("name") if isinstance(loc, dict) else (loc or "")
        addr = ""
        if isinstance(loc, dict):
            a = loc.get("address")
            addr = a if isinstance(a, str) else (a or {}).get("streetAddress", "") if isinstance(a, dict) else ""
        blob = f"{loc_name} {addr}".lower()

        if any(k in blob for k in _NON_CABA):
            continue  # fuera de CABA

        is_yunta = any(k in blob for k in _YUNTA) or "yunta" in url.lower()
        cslug = "yunta-bar" if is_yunta else "comunidad-cinefila"

        venue = addr or loc_name or "Comunidad Cinéfila"
        mslug = _slugify(name) or _slugify(url.split("/")[-1])
        movie = {
            "slug": mslug,
            "title": name,
            "description": (
                f"{ev.get('description') or 'Ciclo de cine de Comunidad Cinéfila.'} "
                f"· Sede: {venue}. Reserva en {url}"
            ).strip(),
            "genres": ["Ciclo"],
            "is_special": True,
            "cartelera_url": url,
        }
        func = {
            "movie": mslug,
            "cinema": cslug,
            "start": start,
            "date": d_s,
            "time": t_s,
            "format": "Ciclo",
            "version": "",
            "buy_url": url,
            "source": "comunidad-cinefila",
        }

        b = buckets.setdefault(
            cslug, {"cinema": CINEMAS[cslug], "movies": {}, "functions": []}
        )
        b["movies"][mslug] = movie
        b["functions"].append(func)
        if on_progress:
            on_progress(mslug, True, f"{d_s} {t_s} @ {cslug}")

    results = [b for b in buckets.values() if b["functions"]]
    return results
