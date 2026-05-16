"""Fuente: cartelera.ar

Cada pagina /cine/<slug> trae un bloque <script type="application/ld+json">
con un @graph que incluye:
  - MovieTheater  (nombre, PostalAddress con addressRegion="CABA", geo, tel)
  - Movie x N     (titulo, url->slug, poster, sinopsis, duracion, genero...)
  - ScreeningEvent x M (startDate ISO, videoFormat, subtitleLanguage,
                        workPresented->Movie @id, location->Cinema @id,
                        offers.url -> link de compra)

Esto nos da datos limpios sin parsear DOM fragil.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

from .fetch import get

BASE = "https://cartelera.ar"
INDEX_URL = f"{BASE}/cines"

_LDJSON_RE = re.compile(
    r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)
_CINE_HREF_RE = re.compile(r'href="/cine/([a-z0-9-]+)(?:\?[^"]*)?"')

# slug-prefix -> cadena (heuristica resiliente; no rompe si cambia)
_CHAIN_BY_PREFIX = {
    "cinemark": "Cinemark Hoyts",
    "hoyts": "Cinemark Hoyts",
    "cinepolis": "Cinépolis",
    "atlas": "Atlas Cines",
    "showcase": "Showcase",
    "multiplex": "Multiplex",
    "cinemacenter": "Multiplex",
    "arteplex": "Multiplex",
    "cinema-devoto": "Independiente",
    "cine-gaumont": "Espacio INCAA",
    "cine-cosmos": "Independiente / UBA",
    "cine-lorca": "Independiente",
    "cinearte-cacodelphia": "Cine de arte",
    "malba": "Museo / Cine de arte",
}

# regiones que consideramos CABA (Capital Federal)
_CABA_REGIONS = {
    "caba",
    "ciudad autonoma de buenos aires",
    "ciudad autónoma de buenos aires",
    "ciudad de buenos aires",
}


def _chain_for(slug: str) -> str:
    for prefix, chain in _CHAIN_BY_PREFIX.items():
        if slug.startswith(prefix):
            return chain
    return "Otro"


def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


def _duration_min(iso: str | None) -> int | None:
    """'PT120M' / 'PT1H56M' -> minutos."""
    if not iso:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso)
    if not m:
        return None
    h = int(m.group(1) or 0)
    mm = int(m.group(2) or 0)
    total = h * 60 + mm
    return total or None


def discover_cinema_slugs() -> list[str]:
    """Lista todos los slugs /cine/<slug> del indice (todo el pais;
    el filtro CABA se aplica despues, por addressRegion)."""
    html = get(INDEX_URL)
    slugs = sorted(set(_CINE_HREF_RE.findall(html)))
    return slugs


def _find_graph(html: str) -> list[dict]:
    """Devuelve el @graph que contiene los ScreeningEvent/Movie/MovieTheater."""
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        graph = data.get("@graph")
        if not graph:
            continue
        types = {item.get("@type") for item in graph}
        if "MovieTheater" in types or "ScreeningEvent" in types:
            return graph
    return []


def _version(ev: dict) -> str:
    if ev.get("subtitleLanguage"):
        return "Subtitulada"
    if ev.get("inLanguage"):
        return "Doblada"
    return ""


def scrape_cinema(slug: str, *, caba_only: bool = True) -> dict | None:
    """Scrapea una sala. Devuelve dict con cinema/movies/functions,
    o None si no es CABA (cuando caba_only) o no tiene datos.
    """
    url = f"{BASE}/cine/{slug}"
    html = get(url)
    graph = _find_graph(html)
    if not graph:
        return None

    by_id: dict[str, dict] = {}
    theater: dict | None = None
    for item in graph:
        if item.get("@id"):
            by_id[item["@id"]] = item
        if item.get("@type") == "MovieTheater" and theater is None:
            theater = item

    if theater is None:
        return None

    addr = theater.get("address") or {}
    region = _norm(addr.get("addressRegion"))
    locality = _norm(addr.get("addressLocality"))
    is_caba = region in _CABA_REGIONS or (
        region == "" and locality in {"buenos aires", "caba"}
        and "provincia" not in locality
    )
    if caba_only and not is_caba:
        return None

    geo = theater.get("geo") or {}
    same = theater.get("sameAs")
    if isinstance(same, list):
        official = same[0] if same else None
    elif isinstance(same, str):
        official = same
    else:
        official = None
    cinema = {
        "slug": slug,
        "name": theater.get("name") or slug,
        "chain": _chain_for(slug),
        "street": addr.get("streetAddress"),
        "locality": addr.get("addressLocality"),
        "region": addr.get("addressRegion"),
        "phone": theater.get("telephone"),
        "lat": geo.get("latitude"),
        "lng": geo.get("longitude"),
        "official_url": official,           # web propia del cine (sameAs)
        "cartelera_url": url,               # pagina del cine en cartelera.ar
        "url": official or url,
        "source_url": url,
    }

    movies: dict[str, dict] = {}
    for item in graph:
        if item.get("@type") != "Movie":
            continue
        murl = item.get("url") or ""
        mslug = murl.rstrip("/").split("/")[-1]
        if not mslug:
            continue
        image = item.get("image")
        if isinstance(image, list) and image:
            poster = image[0].get("url")
        elif isinstance(image, dict):
            poster = image.get("url")
        else:
            poster = image if isinstance(image, str) else None
        director = item.get("director") or {}
        if isinstance(director, list):
            director = director[0] if director else {}
        rating = item.get("aggregateRating") or {}
        trailer = item.get("trailer") or {}
        movies[mslug] = {
            "slug": mslug,
            "title": item.get("name"),
            "alt_title": item.get("alternateName"),
            "poster": poster,
            "description": item.get("description"),
            "genres": item.get("genre") or [],
            "duration_min": _duration_min(item.get("duration")),
            "director": director.get("name") if isinstance(director, dict) else None,
            "rating": rating.get("ratingValue"),
            "date_published": item.get("datePublished"),
            "trailer": trailer.get("contentUrl") if isinstance(trailer, dict) else None,
            "cartelera_url": murl,
        }

    functions: list[dict] = []
    for item in graph:
        if item.get("@type") != "ScreeningEvent":
            continue
        work = item.get("workPresented") or {}
        mref = work.get("@id", "")
        # @id -> https://cartelera.ar/pelicula/<slug>#movie
        mslug = mref.split("/pelicula/")[-1].split("#")[0] if "/pelicula/" in mref else ""
        start = item.get("startDate")
        if not (mslug and start):
            continue
        try:
            dt = datetime.fromisoformat(start)
            date_s = dt.date().isoformat()
            time_s = dt.strftime("%H:%M")
        except ValueError:
            date_s, time_s = start[:10], start[11:16]
        offers = item.get("offers") or {}
        functions.append(
            {
                "movie": mslug,
                "cinema": slug,
                "start": start,
                "date": date_s,
                "time": time_s,
                "format": item.get("videoFormat") or "2D",
                "version": _version(item),
                "buy_url": offers.get("url") if isinstance(offers, dict) else None,
            }
        )

    if not functions:
        return None

    return {"cinema": cinema, "movies": movies, "functions": functions}


def scrape_all(
    slugs: Iterable[str] | None = None,
    *,
    on_progress=None,
) -> list[dict]:
    """Scrapea todas las salas CABA. on_progress(slug, ok, info)."""
    if slugs is None:
        slugs = discover_cinema_slugs()
    slugs = list(slugs)
    results: list[dict] = []
    for slug in slugs:
        try:
            res = scrape_cinema(slug)
        except Exception as exc:  # una sala caida no frena el run
            if on_progress:
                on_progress(slug, False, f"error: {exc}")
            continue
        if res is None:
            if on_progress:
                on_progress(slug, False, "no-CABA / sin funciones")
            continue
        results.append(res)
        if on_progress:
            on_progress(
                slug,
                True,
                f"{len(res['movies'])} pelis, {len(res['functions'])} funciones",
            )
    return results
