"""Fuente secundaria: espacios culturales / ciclos que NO estan en
cartelera.ar (Palacio Libertad/exCCK, Biblioteca del Congreso,
Biblioteca Nacional, Centro Cultural Borges, Casa del Bicentenario,
Club Lucero, Overo Bar, etc.).

Su programacion cambia por mes/ciclo (no diaria) y no tiene datos
machine-readable, asi que se cura a mano en data/extras.json con el
MISMO esquema que produce cartelera_ar.scrape_cinema(), y el merger
lo integra al store.

data/extras.json:
{
  "cinemas":   [ {slug,name,chain,street,locality,region,...} ],
  "movies":    [ {slug,title,description,...} ],
  "functions": [ {movie,cinema,start,date,time,format,version,buy_url} ]
}
"""
from __future__ import annotations

import json
import os

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "extras.json"
)


def load_extras(path: str = DEFAULT_PATH) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    data.setdefault("cinemas", [])
    data.setdefault("movies", [])
    data.setdefault("functions", [])
    return data
