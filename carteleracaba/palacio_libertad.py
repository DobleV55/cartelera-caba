"""Fuente: Palacio Libertad (exCCK) — cine.

Palacio Libertad publica su programación con el plugin WordPress
"Modern Events Calendar" (MEC). La categoría "Cine" (id 153) lista los
eventos/ciclos; cada página `/events/<slug>/` trae:
  - JSON-LD @type Event con startDate/endDate y location.name (la sala).
  - Un bloque "Agenda" en el cuerpo con el detalle día por día, p.ej.:
      Domingo 7 de junio  15 h: El bello Sergio  17:30 h: Que la bestia muera
    De ahí salen las funciones individuales (fecha + hora + título).

Si un evento no tiene "Agenda" parseable, se cae a una única entrada con
la fecha de inicio (el ciclo como tal). Solo se devuelven eventos futuros.
"""
from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from .fetch import get

BASE = "https://palaciolibertad.gob.ar"
CINE_CATEGORY = 153

CINEMA = {
    "slug": "palacio-libertad",
    "name": "Palacio Libertad (exCCK)",
    "chain": "Centro cultural",
    "street": "Sarmiento 151",
    "locality": "San Nicolás",
    "region": "CABA",
    "phone": None,
    "lat": -34.6033,
    "lng": -58.3702,
    "url": f"{BASE}/cine/",
    "source_url": f"{BASE}/cine/",
}

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_DAYS = "lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo"

# "Domingo 7 de junio" -> captura día y mes (con o sin nombre de día delante)
_DATE_RE = re.compile(
    rf"(?:{_DAYS})?\s*(\d{{1,2}})\s+de\s+(" + "|".join(_MONTHS) + r")",
    re.I,
)
# token de horario: "15 h" / "17:30 h" / "20.30 h"
_TIME_RE = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*h\b", re.I)


def _clean(markup: str) -> str:
    # unescape primero (algunos títulos vienen doble-encodeados, p.ej.
    # "&lt;i&gt;Colorada&lt;/i&gt;"), luego sacar tags y colapsar espacios.
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(markup))).strip()


def _slug(title: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def _event_jsonld(html: str) -> dict | None:
    for b in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            j = json.loads(b)
        except json.JSONDecodeError:
            continue
        if isinstance(j, dict) and "Event" in str(j.get("@type", "")):
            return j
    return None


def _event_body(html: str) -> str:
    m = re.search(r'class="[^"]*mec-single-event-description[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S)
    if not m:
        m = re.search(r'class="[^"]*event-content[^"]*"[^>]*>(.*?)</article>', html, re.S)
    # acotar para evitar regex sobre HTML gigante (algunos posts traen
    # bloques enormes que no son la agenda)
    return _clean(m.group(1))[:6000] if m else ""


def _shows_in(block: str) -> list[tuple[str, str]]:
    """[(‘HH:MM’, titulo)] — parte el bloque por cada token de horario.
    Lineal (sin backtracking): el título es el texto entre un horario y
    el siguiente."""
    times = list(_TIME_RE.finditer(block))
    out: list[tuple[str, str]] = []
    for i, tm in enumerate(times):
        end = times[i + 1].start() if i + 1 < len(times) else len(block)
        hh = int(tm.group(1))
        mm = tm.group(2) or "00"
        if hh > 23:
            continue
        title = block[tm.end():end].strip(" .:-—–—")
        title = re.sub(r"\s+", " ", title)
        if 2 <= len(title) <= 120:
            out.append((f"{hh:02d}:{mm}", title))
    return out


def _parse_agenda(body: str, year: int) -> list[tuple[str, str, str]]:
    """Devuelve [(date_iso, 'HH:MM', titulo_film)] del bloque Agenda."""
    out: list[tuple[str, str, str]] = []
    # cortar desde "Agenda" si existe (evita parsear la sinopsis)
    idx = body.lower().find("agenda")
    seg = body[idx + 6:] if idx >= 0 else body
    marks = list(_DATE_RE.finditer(seg))
    if not marks:
        return out
    for i, dm in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(seg)
        day = int(dm.group(1))
        month = _MONTHS[dm.group(2).lower()]
        try:
            date_iso = date(year, month, day).isoformat()
        except ValueError:
            continue
        for time_s, title in _shows_in(seg[dm.end():end]):
            out.append((date_iso, time_s, title))
    return out


def _scrape_event(slug: str, link: str, today: str) -> dict | None:
    html = get(link, insecure=True, timeout=25)
    ld = _event_jsonld(html)
    if not ld:
        return None
    start = (ld.get("startDate") or "")[:10]
    end = (ld.get("endDate") or start)[:10]
    if not start or end < today:           # ciclo ya terminado
        return None
    year = int(start[:4])
    sala = ((ld.get("location") or {}).get("name") or "").strip()
    image = ld.get("image") or None
    body = _event_body(html)
    cycle_title = _clean(ld.get("name", "")) or slug

    agenda = _parse_agenda(body, year)
    movies: dict[str, dict] = {}
    functions: list[dict] = []

    def add(film_title: str, date_iso: str, time_s: str | None):
        mslug = _slug(film_title) or slug
        if mslug not in movies:
            movies[mslug] = {
                "slug": mslug,
                "title": film_title,
                "description": (body[:300] if film_title == cycle_title else
                                f"{cycle_title} — Palacio Libertad. {body[:200]}"),
                "genres": ["Cine"],
                "poster": image,
                "is_special": True,
            }
        functions.append({
            "movie": mslug,
            "cinema": CINEMA["slug"],
            "start": f"{date_iso}T{time_s or '00:00'}:00-03:00",
            "date": date_iso,
            "time": time_s or "",
            "format": f"Cine — {sala}" if sala else "Cine",
            "version": "",
            "buy_url": link,
            "source": "palacio-libertad",
        })

    if agenda:
        for date_iso, time_s, film in agenda:
            if date_iso >= today:
                add(film, date_iso, time_s)
    else:
        # sin agenda detallada: el ciclo como una sola entrada en su inicio
        add(cycle_title, max(start, today), None)

    if not functions:
        return None
    return {"movies": movies, "functions": functions}


def scrape(*, on_progress=None, workers: int = 6) -> list[dict]:
    """Scrapea la cartelera de cine de Palacio Libertad. Devuelve lista con
    un único dict {cinema, movies, functions} (mismo shape que las otras
    fuentes), o lista vacía si falla."""
    today = date.today().isoformat()
    # ordenado por fecha de publicación desc: los próximos ciclos están
    # arriba. 50 alcanza de sobra para la ventana vigente y evita bajar
    # decenas de páginas de eventos ya pasados.
    listing = get(
        f"{BASE}/wp-json/wp/v2/mec-events?mec_category={CINE_CATEGORY}"
        f"&per_page=50&orderby=date&order=desc&_fields=slug,link",
        insecure=True, timeout=30,
    )
    events = json.loads(listing)

    movies: dict[str, dict] = {}
    functions: list[dict] = []
    seen_events = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_scrape_event, e["slug"], e["link"], today): e["slug"]
                for e in events if e.get("link")}
        for fut in as_completed(futs):
            try:
                res = fut.result()
            except Exception:
                res = None
            if not res:
                continue
            seen_events += 1
            for ms, m in res["movies"].items():
                movies.setdefault(ms, m)
            functions += res["functions"]

    if not functions:
        if on_progress:
            on_progress("palacio-libertad", False, "sin funciones futuras")
        return []
    if on_progress:
        on_progress("palacio-libertad", True,
                    f"{seen_events} ciclos, {len(movies)} films, {len(functions)} funciones")
    return [{"cinema": CINEMA, "movies": movies, "functions": functions}]
