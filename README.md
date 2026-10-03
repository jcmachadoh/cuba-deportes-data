# cuba-deportes-data

Pipeline de datos para la app deportiva para cubanos. Cubre béisbol, fútbol,
voleibol, UFC, boxeo y ajedrez, más la sección "Cubanos por el mundo".
No usa servidor propio: **GitHub Actions** recolecta y genera los JSON, y un
**Cloudflare Worker de solo archivos estáticos** los publica. Todas las fuentes
son públicas y gratuitas.

```
fuentes (APIs JSON / HTML) ──► GitHub Actions (Python) ──► data/ + state/ (git)
                                                     └──► build ──► public/ ──► wrangler deploy ──► Cloudflare
```

## Uso local

```bash
pip install -r requirements.txt          # Python 3.12+; cairosvg necesita libcairo2
export PIPELINE_CONTACT="https://github.com/<usuario>/<repo>"   # va en el User-Agent

python -m pipeline.run collect --profile full                   # temporada actual
python -m pipeline.run collect --profile backfill --only baseball.mlb,soccer.esp-1
python -m pipeline.run collect --profile live --sport baseball  # solo clasificaciones
python -m pipeline.run enrich                                   # cubanos vía Wikidata
python -m pipeline.run logos                                    # WebP 256/64
python -m pipeline.run photos --limit 200
python -m pipeline.run build                                    # genera public/
python -m pipeline.run report
pytest -q
```

Variables opcionales: `HTTP_CACHE_TTL` (segundos de caché HTTP en `.cache/`,
útil al desarrollar), `PHOTOS_WIKIDATA_BATCH`, y las de R2 (`R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE`) para
copiar a R2 las fotos de Commons. Sin R2, se enlaza la URL original.

## Perfiles

| Perfil | Qué hace | Cuándo |
|---|---|---|
| `live` | clasificaciones y rankings de competiciones activas este mes | cada 2 h |
| `full` | todo lo de la temporada actual (equipos, plantillas, rankings, torneos) + Wikidata + logos | diario |
| `photos` | resuelve fotos pendientes (primero los cubanos) | diario |
| `logos` | logos nuevos o vencidos (30 días) | lunes |
| `backfill` | temporadas pasadas según `history_seasons` | manual |

## Despliegue

URL pública: **https://cuba-deportes-data.cuba-deportes.workers.dev** (por ejemplo `/v1/manifest.json`).

`python -m pipeline.deploy` sube `public/` con la API de Cloudflare (no necesita Node);
solo envía los archivos que cambiaron. `npx wrangler deploy --config worker/wrangler.jsonc`
es equivalente.

1. Crear el repositorio **público** (Actions gratis sin límite de minutos) y subir este código.
2. En Cloudflare: crear un API token con la plantilla "Edit Cloudflare Workers".
3. En GitHub → Settings → Secrets and variables → Actions:
   - Secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` (y los de R2 si se usan).
   - Variables: `PIPELINE_CONTACT` (URL del repo o un correo), `R2_PUBLIC_BASE` (opcional).
4. Ejecutar a mano el workflow `pipeline` con `profile=backfill` y después con `profile=photos`.
   Los cron se encargan del resto. Los commits de datos cuentan como actividad,
   así que los cron no se desactivan por inactividad.

## Añadir una competición

Editar `config/competitions.yml`. Si la fuente ya tiene adaptador (por ejemplo
otra liga de ESPN), basta con una entrada nueva. Si es una fuente nueva, crear
`pipeline/adapters/<nombre>.py` con `collect(comp, season, ctx) -> Bundle`,
guardar una página de ejemplo en `tests/fixtures/` y añadir su prueba.

## Documentación

- `docs/pantallas.md`: pantallas de la app y el JSON que usa cada una, y la sincronización del primer arranque.
- `docs/modelo-datos.md`: estructura, IDs y reglas de flexibilidad.
- `docs/estado-fuentes.md`: qué da cada fuente, limitaciones conocidas y el resultado de la última ejecución.
