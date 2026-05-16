"""Modelo + store con deduplicacion.

Esquema de data/cartelera.json:
{
  "generated_at": ISO,
  "sources": ["cartelera.ar", "extras"],
  "cinemas": { "<slug>": {...} },
  "movies":  { "<slug>": {... , "_cinemas":[slug...] } },
  "functions": [ {movie,cinema,start,date,time,format,version,buy_url} ]
}

Dedup:
  - movies  -> por slug (merge de metadata, gana el valor no nulo)
  - cinemas -> por slug
  - functions -> por (movie, cinema, start, format, version)

Re-ejecuciones: hace merge con el store previo y poda funciones
con fecha < hoy (rolling window).
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

_TZ = timezone.utc


def _func_key(f: dict) -> tuple:
    return (f["movie"], f["cinema"], f["start"], f.get("format", ""), f.get("version", ""))


def _merge_movie(dst: dict, src: dict) -> dict:
    out = dict(dst)
    for k, v in src.items():
        if v in (None, "", [], {}):
            continue
        if not out.get(k):
            out[k] = v
    return out


def build_store(results: list[dict], extras: dict | None = None) -> dict:
    cinemas: dict[str, dict] = {}
    movies: dict[str, dict] = {}
    funcs: dict[tuple, dict] = {}

    for res in results:
        c = res["cinema"]
        cinemas[c["slug"]] = c
        for mslug, m in res["movies"].items():
            movies[mslug] = _merge_movie(movies.get(mslug, {}), m)
        for f in res["functions"]:
            funcs[_func_key(f)] = f

    if extras:
        for c in extras.get("cinemas", []):
            cinemas.setdefault(c["slug"], c)
        for m in extras.get("movies", []):
            movies[m["slug"]] = _merge_movie(movies.get(m["slug"], {}), m)
        for f in extras.get("functions", []):
            funcs[_func_key(f)] = f

    # backref: en que cines esta cada peli
    for m in movies.values():
        m["_cinemas"] = []
    for f in funcs.values():
        m = movies.get(f["movie"])
        if m is not None and f["cinema"] not in m["_cinemas"]:
            m["_cinemas"].append(f["cinema"])

    return {
        "generated_at": datetime.now(_TZ).isoformat(),
        "sources": ["cartelera.ar"] + (["extras"] if extras else []),
        "cinemas": dict(sorted(cinemas.items())),
        "movies": dict(sorted(movies.items(), key=lambda kv: (kv[1].get("title") or kv[0]))),
        "functions": sorted(
            funcs.values(), key=lambda f: (f["date"], f["time"], f["cinema"])
        ),
    }


def load_store(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def merge_with_previous(new: dict, prev: dict | None, *, prune_past: bool = True) -> dict:
    """Acumula funciones del store previo + nuevas, dedup, poda pasado."""
    if not prev:
        merged = new
    else:
        cinemas = {**prev.get("cinemas", {}), **new["cinemas"]}
        movies = dict(prev.get("movies", {}))
        for slug, m in new["movies"].items():
            movies[slug] = _merge_movie(movies.get(slug, {}), m)
        funcs: dict[tuple, dict] = {}
        for f in prev.get("functions", []) + new["functions"]:
            funcs[_func_key(f)] = f
        merged = {
            "generated_at": new["generated_at"],
            "sources": new["sources"],
            "cinemas": cinemas,
            "movies": movies,
            "functions": list(funcs.values()),
        }

    if prune_past:
        today = date.today().isoformat()
        merged["functions"] = [f for f in merged["functions"] if f["date"] >= today]

    # recomputar backrefs y orden
    for m in merged["movies"].values():
        m["_cinemas"] = []
    live_movies = set()
    live_cinemas = set()
    for f in merged["functions"]:
        live_movies.add(f["movie"])
        live_cinemas.add(f["cinema"])
        m = merged["movies"].get(f["movie"])
        if m is not None and f["cinema"] not in m["_cinemas"]:
            m["_cinemas"].append(f["cinema"])

    # descartar pelis/cines que ya no tienen ninguna funcion vigente
    merged["movies"] = {
        s: m for s, m in merged["movies"].items() if s in live_movies
    }
    merged["cinemas"] = {
        s: c for s, c in merged["cinemas"].items() if s in live_cinemas
    }
    merged["movies"] = dict(
        sorted(merged["movies"].items(), key=lambda kv: (kv[1].get("title") or kv[0]))
    )
    merged["cinemas"] = dict(sorted(merged["cinemas"].items()))
    merged["functions"] = sorted(
        merged["functions"], key=lambda f: (f["date"], f["time"], f["cinema"])
    )
    return merged


def save_store(store: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def stats(store: dict) -> str:
    nf = len(store["functions"])
    nm = len(store["movies"])
    nc = len(store["cinemas"])
    dates = sorted({f["date"] for f in store["functions"]})
    rng = f"{dates[0]}..{dates[-1]}" if dates else "—"
    return f"{nc} cines · {nm} pelis · {nf} funciones · fechas {rng}"
