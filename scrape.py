#!/usr/bin/env python3
"""Cartelera CABA — scraper principal.

Recorre TODOS los cines (cartelera.ar), se queda con los de CABA,
deduplica peliculas/cines/funciones y acumula en data/cartelera.json.
Pensado para correr por cron una vez al dia.

Uso:
  python3 scrape.py                # run normal (merge + poda pasado)
  python3 scrape.py --workers 8    # mas paralelismo
  python3 scrape.py --no-extras    # sin centros culturales curados
  python3 scrape.py --full         # no poda funciones pasadas
  python3 scrape.py --only cinemark-palermo,cine-gaumont
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from carteleracaba import cartelera_ar, model  # noqa: E402
from carteleracaba.extras import load_extras  # noqa: E402

DATA_DIR = os.path.join(HERE, "data")
STORE_PATH = os.path.join(DATA_DIR, "cartelera.json")
CSV_PATH = os.path.join(DATA_DIR, "cartelera.csv")


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def export_csv(store: dict, path: str) -> None:
    cols = [
        "fecha", "hora", "pelicula", "cine", "cadena", "barrio",
        "direccion", "formato", "version", "duracion_min", "genero",
        "link_compra",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for f in store["functions"]:
            m = store["movies"].get(f["movie"], {})
            c = store["cinemas"].get(f["cinema"], {})
            w.writerow([
                f["date"], f["time"], m.get("title", f["movie"]),
                c.get("name", f["cinema"]), c.get("chain", ""),
                c.get("locality", ""), c.get("street", ""),
                f.get("format", ""), f.get("version", ""),
                m.get("duration_min", ""),
                "; ".join(m.get("genres", []) or []),
                f.get("buy_url", ""),
            ])


def main() -> int:
    ap = argparse.ArgumentParser(description="Scraper de cartelera de cine CABA")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-extras", action="store_true")
    ap.add_argument("--full", action="store_true", help="no podar funciones pasadas")
    ap.add_argument("--only", default="", help="slugs separados por coma")
    ap.add_argument("--out", default=STORE_PATH)
    args = ap.parse_args()

    t0 = time.time()
    if args.only:
        slugs = [s.strip() for s in args.only.split(",") if s.strip()]
        _log(f"slugs forzados: {slugs}")
    else:
        _log("descubriendo cines en cartelera.ar/cines ...")
        slugs = cartelera_ar.discover_cinema_slugs()
        _log(f"{len(slugs)} cines en el indice (todo el pais)")

    results: list[dict] = []
    ok = caba = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(cartelera_ar.scrape_cinema, s): s for s in slugs}
        for fut in as_completed(futs):
            slug = futs[fut]
            ok += 1
            try:
                res = fut.result()
            except Exception as exc:
                _log(f"  ✗ {slug}: {exc}")
                continue
            if res is None:
                continue
            caba += 1
            results.append(res)
            _log(
                f"  ✓ {slug:32} {len(res['movies']):>2} pelis "
                f"{len(res['functions']):>3} func "
                f"[{res['cinema'].get('locality')}]"
            )

    _log(f"procesados {ok}/{len(slugs)} · CABA con funciones: {caba}")

    extras = None if args.no_extras else load_extras()
    if extras:
        _log(
            f"extras: {len(extras['cinemas'])} espacios culturales, "
            f"{len(extras['functions'])} funciones curadas"
        )

    new_store = model.build_store(results, extras=extras)
    prev = model.load_store(args.out)
    final = model.merge_with_previous(
        new_store, prev, prune_past=not args.full
    )

    model.save_store(final, args.out)
    export_csv(final, CSV_PATH)

    # espejo para GitHub Pages (docs/data) si existe la carpeta docs
    docs_data = os.path.join(HERE, "docs", "data")
    if os.path.isdir(os.path.join(HERE, "docs")):
        os.makedirs(docs_data, exist_ok=True)
        model.save_store(final, os.path.join(docs_data, "cartelera.json"))
        export_csv(final, os.path.join(docs_data, "cartelera.csv"))
        _log(f"DOCS  -> {docs_data}/cartelera.json")

    _log("STORE: " + model.stats(final))
    _log(f"JSON  -> {args.out}")
    _log(f"CSV   -> {CSV_PATH}")
    _log(f"listo en {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
