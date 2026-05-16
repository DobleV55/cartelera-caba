# Cartelera CABA 🎬

Scraper + web de **todas las películas en cartelera de cines de Capital Federal**,
con funciones por **día, horario, sala, formato y versión**, deduplicadas por película.
Pensado para correr por **cron diario** y servir una **página web**.

## Qué hace

1. Recorre **todos los cines** del índice de `cartelera.ar` (≈83, todo el país).
2. Se queda **solo con los de CABA** (filtro por `addressRegion = CABA` del JSON-LD).
3. De cada sala extrae, desde el JSON-LD estructurado:
   - **Cine**: nombre, cadena, dirección, barrio, teléfono, geo (lat/lng).
   - **Película**: título, título original, póster, sinopsis, duración, género,
     director, rating, tráiler. **Una sola vez** (dedup por slug).
   - **Funciones**: fecha, hora, formato (2D/3D/4DX/XD), versión
     (Subtitulada/Doblada), link de compra.
4. Scrapea **Comunidad Cinéfila** (`comunidadcinefila.org`, sitio Wix Events):
   lee `event-pages-sitemap.xml` y el JSON-LD `@type Event` de cada
   `/event-details/<slug>`. Detecta **automáticamente** funciones futuras
   en CABA (Yunta Bar / sedes itinerantes) sin reverse-engineering de la
   API privada de Wix. Solo muestra eventos **publicados y futuros**.
5. Suma **centros culturales / ciclos** curados a mano (`data/extras.json`):
   Palacio Libertad (exCCK), Biblioteca del Congreso, Biblioteca Nacional,
   Centro Cultural Borges, Casa del Bicentenario, Club Lucero.
6. **Acumula y deduplica** en `data/cartelera.json`. Cada función lleva
   `source`: las de `cartelera.ar` se **acumulan hacia adelante** (esa
   fuente solo publica hoy/mañana); las de `extras` y `comunidad-cinefila`
   son **snapshots autoritativos** que se regeneran enteros cada run (si
   una entrada se borra de la fuente, desaparece). Poda fechas pasadas.
7. Exporta también `data/cartelera.csv`.

Cobertura CABA real hoy: Cinemark/Hoyts (Palermo, Caballito, Puerto Madero,
Abasto, Dot Baires), Cinépolis (Recoleta, Houssay), Atlas (Caballito, Flores,
Liniers, Patio Bullrich, Alcorta), Showcase Belgrano, Multiplex (Belgrano,
Lavalle), Cine Gaumont, Cosmos, Cacodelphia, MALBA + los 6 espacios culturales.
*(Las salas que un día no tienen funciones aparecen automáticamente cuando sí
las tienen — el cron las va incorporando.)*

## Uso

```bash
python3 scrape.py                 # scrapea, dedup, merge, escribe data/
python3 scrape.py --workers 8     # más paralelismo (default 6)
python3 scrape.py --no-extras     # sin centros culturales
python3 scrape.py --full          # no podar funciones pasadas
python3 scrape.py --only cine-gaumont,cinemark-palermo
```

Ver la web:

```bash
python3 web/server.py             # http://localhost:8777/web/
```

## Cron

**macOS (launchd, recomendado)** — corre 08:05 y 15:05:

```bash
cp cron/com.carteleracaba.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.carteleracaba.daily.plist
```

**crontab (Linux/macOS)** — `crontab -e`:

```
5 8,15 * * *  /bin/bash /Users/valenvila/cartelera-caba/cron/run.sh
```

Logs en `data/cron.log` (se rota solo).

## Estructura

```
cartelera-caba/
├── scrape.py                 # orquestador (CLI)
├── carteleracaba/
│   ├── fetch.py              # HTTP stdlib (UA, reintentos, gzip, TLS laxo)
│   ├── cartelera_ar.py       # parser JSON-LD de cartelera.ar
│   ├── extras.py             # loader de centros culturales
│   └── model.py              # dedup + merge + store + stats
├── data/
│   ├── cartelera.json        # store deduplicado (lo lee la web)
│   ├── cartelera.csv         # export plano
│   └── extras.json           # ciclos culturales curados (editable)
├── web/
│   ├── index.html            # SPA: filtros por fecha/cadena/cine + búsqueda
│   └── server.py             # preview local
└── cron/
    ├── run.sh                # entrypoint con logs
    └── com.carteleracaba.daily.plist
```

## Esquema `data/cartelera.json`

```jsonc
{
  "generated_at": "ISO-8601",
  "sources": ["cartelera.ar", "extras"],
  "cinemas":  { "<slug>": { "name","chain","street","locality","lat","lng","phone","url" } },
  "movies":   { "<slug>": { "title","alt_title","poster","description",
                            "genres","duration_min","director","rating",
                            "trailer","_cinemas":[...] } },
  "functions": [ { "movie","cinema","start","date","time",
                   "format","version","buy_url" } ]
}
```

Dedup: películas y cines por `slug`; funciones por
`(movie, cinema, start, format, version)`.

## Mantenimiento

- Programación de centros culturales: editar `data/extras.json` (mismo esquema)
  cuando cambien los ciclos mensuales.
- Si `cartelera.ar` cambia el JSON-LD, ajustar `carteleracaba/cartelera_ar.py`
  (única pieza acoplada a la fuente). Una sala que falla no frena el run.

## Notas

- Sin dependencias (solo stdlib) → portable para cron.
- `cartelera.ar` publica hoy+mañana por sala; el cron diario acumula la
  ventana completa hacia adelante y descarta el pasado.
- Los horarios cambian (renovación de cartelera los jueves); el cron mantiene
  el store fresco.
