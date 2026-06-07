"""Fuente: Cinemark Hoyts Argentina (BFF JSON).

cartelera.ar solo publica el día de hoy. El BFF de Cinemark
(`bff.cinemark.com.ar/api`) expone ~18 días de funciones por sala, así que
para los 5 cines Cinemark/Hoyts de CABA usamos esta fuente (semana completa)
en lugar de cartelera.ar.

Endpoints (todos requieren header `country: AR`):
  /cinema/theaters                  -> salas (id, slug, dirección, geo, location)
  /cinema/movies                    -> pelis en cartelera (slug, poster, runTime…)
  /cinema/movies/slug/<slug>        -> detalle (synopsis, genres, trailerUrl)
  /cinema/showtimes?theater=<id>    -> funciones (sessionDateTime, format, lang…)

Join showtime->movie por `corporateId`.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from .fetch import get

BASE = "https://bff.cinemark.com.ar/api"
WEB = "https://www.cinemark.com.ar"
_HEADERS = {"country": "AR"}

# theater.slug (API) -> (slug que ya usa cartelera.ar, nombre display)
# Mantener los mismos slugs evita cines duplicados y conserva el filtro web.
_SLUG_MAP = {
    "palermo": ("cinemark-palermo", "Cinemark Palermo"),
    "caballito": ("cinemark-caballito", "Cinemark Caballito"),
    "puertomadero": ("cinemark-puerto-madero", "Cinemark Puerto Madero"),
    "abasto": ("hoyts-abasto", "Hoyts Abasto"),
    "dot": ("hoyts-dot-baires", "Hoyts Dot Baires"),
}
CHAIN = "Cinemark Hoyts"

# slugs de cartelera.ar que esta fuente reemplaza (para excluirlos allá)
COVERS_SLUGS = {slug for slug, _ in _SLUG_MAP.values()}


def _api(path: str) -> dict | list:
    body = get(f"{BASE}{path}", headers=_HEADERS)
    return json.loads(body)


def _data(payload) -> list:
    if isinstance(payload, dict):
        return payload.get("data") or []
    return payload or []


def _is_caba(theater: dict) -> bool:
    loc = (theater.get("location") or {}).get("name", "").lower()
    city = (theater.get("city") or "").lower()
    return loc.startswith("ciudad") or city == "caba"


def _version(short: str | None) -> str:
    s = (short or "").upper()
    if s == "SUB":
        return "Subtitulada"
    if s in ("CAST", "ESP", "DOB"):
        return "Doblada"
    return ""


def _movie_from(meta: dict, slug: str) -> dict:
    """Arma el dict peli con el esquema del store a partir del detalle/lista."""
    genres = meta.get("genres") or []
    if genres and isinstance(genres[0], dict):
        genres = [g.get("name") for g in genres if g.get("name")]
    return {
        "slug": slug,
        "title": meta.get("title"),
        "alt_title": None,
        "poster": meta.get("posterUrl"),
        "description": meta.get("synopsis"),
        "genres": genres,
        "duration_min": meta.get("runTime") or None,
        "director": meta.get("director"),
        "rating": meta.get("rating"),
        "trailer": meta.get("trailerUrl"),
        "cartelera_url": f"{WEB}/pelicula/{slug}",
    }


def scrape_all(*, on_progress=None, workers: int = 6) -> list[dict]:
    """Scrapea los cines Cinemark/Hoyts de CABA. Devuelve lista de dicts
    {cinema, movies, functions} (mismo shape que cartelera_ar)."""
    theaters = [t for t in _data(_api("/cinema/theaters")) if _is_caba(t)]

    # catálogo de pelis (corporateId -> slug/meta básica)
    by_corp: dict[str, dict] = {}
    for m in _data(_api("/cinema/movies")):
        if m.get("corporateId"):
            by_corp[str(m["corporateId"])] = m

    # enriquecer con detalle (synopsis/genres/trailer) en paralelo
    detail: dict[str, dict] = {}

    def _fetch_detail(slug: str):
        try:
            return slug, (_data(_api(f"/cinema/movies/slug/{slug}")) or
                          _api(f"/cinema/movies/slug/{slug}"))
        except Exception:
            return slug, None

    slugs = {m["slug"] for m in by_corp.values() if m.get("slug")}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(_fetch_detail, s) for s in slugs]):
            slug, d = fut.result()
            if isinstance(d, dict) and d:
                detail[slug] = d

    results: list[dict] = []
    for t in theaters:
        api_slug = t.get("slug", "")
        slug, name = _SLUG_MAP.get(
            api_slug, (f"cinemarkhoyts-{api_slug}", t.get("name") or api_slug)
        )
        cinema = {
            "slug": slug,
            "name": name,
            "chain": CHAIN,
            "street": t.get("address"),
            "locality": t.get("city") or "CABA",
            "region": "CABA",
            "phone": None,
            "lat": t.get("latitude"),
            "lng": t.get("longitude"),
            "official_url": f"{WEB}/cine/{api_slug}",
            "cartelera_url": f"{WEB}/cine/{api_slug}",
            "url": f"{WEB}/cine/{api_slug}",
            "source_url": f"{BASE}/cinema/showtimes?theater={t.get('id')}",
        }

        try:
            shows = _data(_api(f"/cinema/showtimes?theater={t.get('id')}"))
        except Exception as exc:
            if on_progress:
                on_progress(slug, False, f"error showtimes: {exc}")
            continue

        movies: dict[str, dict] = {}
        functions: list[dict] = []
        for s in shows:
            corp = str(s.get("corporateId") or "")
            cat = by_corp.get(corp, {})
            mslug = cat.get("slug")
            if not mslug:
                continue
            if mslug not in movies:
                meta = {**cat, **detail.get(mslug, {})}
                movies[mslug] = _movie_from(meta, mslug)
            date_s = s.get("sessionDisplayDate") or s.get("sessionDateTime", "")[:10]
            time_s = (s.get("sessionDateTime") or "")[11:16]
            if not (date_s and time_s):
                continue
            lang = (s.get("language") or {}).get("shortName")
            functions.append({
                "movie": mslug,
                "cinema": slug,
                "start": f"{date_s}T{time_s}:00-03:00",
                "date": date_s,
                "time": time_s,
                "format": s.get("sessionFormat") or "2D",
                "version": _version(lang),
                "buy_url": f"{WEB}/pelicula/{mslug}",
                "source": "cinemark",
            })

        if not functions:
            if on_progress:
                on_progress(slug, False, "sin funciones")
            continue
        results.append({"cinema": cinema, "movies": movies, "functions": functions})
        if on_progress:
            on_progress(slug, True, f"{len(movies)} pelis, {len(functions)} funciones")

    return results
