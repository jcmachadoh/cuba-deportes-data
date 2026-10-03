# Pantallas de la app y archivos JSON que consume

Base: `https://<worker>.workers.dev` (o dominio propio). Todo es estático: la app
solo hace `GET` y cachea. Rutas relativas a `/v1/` salvo `/media/`.

## Primer arranque (sincronización)

1. `GET /v1/manifest.json` → lista `files: {ruta: hash}`. Guardar localmente.
2. `GET /v1/media.json` → `packs` por deporte (`/media/packs/logos-{sport}-{hash}.zip`)
   y `logos: {entityId: {hash, sizes}}`. Descargar los packs (WebP 256 y 64 px),
   descomprimir en almacenamiento interno. Ruta de un logo: `logoPath` con
   `{hash}` y `{size}`.
3. `GET /v1/sports.json` → catálogo de deportes, competiciones, grupos de plantilla
   y etiquetas de estadísticas (en español).
4. En cada apertura posterior: volver a pedir `manifest.json` (cache 60 s) y
   descargar solo los archivos cuyo hash cambió. Si cambia el hash de un pack,
   bajar el pack nuevo.

Las fotos de personas NO van en packs: cada persona trae `photo.url` (+ `credit`,
`license` si la fuente lo exige). Se cargan bajo demanda con caché de imágenes
(Coil/Glide). Si falta `photo`, mostrar iniciales.

## Mapa de pantallas

| # | Pantalla | Archivo(s) | Notas |
|---|---|---|---|
| 1 | Inicio / Deportes | `sports.json`, `status.json` | Tarjetas por deporte; acceso a "Cubanos por el mundo". |
| 2 | Lista de competiciones de un deporte | `sports.json` (`competitions[]`) | Agrupar por `tags` (p. ej. `invierno`, `caribe`, `europa`). |
| 3 | Competición | `competitions/{id}.json` | Temporadas (`seasons[]`, la actual con `current: true`). |
| 3a | Clasificación | `competitions/{id}/seasons/{s}/standings.json` | `groups[]` → `rows[]` con `stats` (claves de `sports.json`). Equipos hidratados (`team.name`, `team.logo`). |
| 3b | Equipos de la temporada | `competitions/{id}/seasons/{s}/teams.json` | Lista para navegar al equipo. |
| 3c | Rankings (UFC, WBC, FIDE) | `competitions/{id}/seasons/{s}/rankings/{rankingId}.json` | `entries[]` con `person` hidratada; campeón con `extra.champion`. |
| 3d | Torneos (ajedrez) | `competitions/{id}/seasons/{s}/events/{eventId}.json` | Clasificación final/provisional, jugadores con Elo y federación. |
| 4 | Equipo | `teams/{id}.json` | Datos fijos + `seasons[]` (historial por competición/temporada). |
| 4a | Plantilla por posición | `teams/{id}/seasons/{s}/roster.json` | `groups[]` en el orden de `rosterGroups` del deporte (Lanzadores, Receptores… / Porteros, Defensas… / Cuerpo técnico). |
| 5 | Jugador | `persons/{shard}.json` | `shard = sha1(personId)[:2]`. Contiene todas las personas del shard; la app guarda el shard en caché. |
| 6 | Cubanos por el mundo | `cubanos/index.json` | `persons[]` con `abroad`, `sports`, `links[]` (competición, equipo o ranking, posición). Filtro por deporte con `bySport`/`abroadBySport`. |
| 7 | Ajedrez | `competitions/chess.fide-ranking/...rankings/*` (Top 100 open, mujeres, junior, niñas), `chess.fide-cuba` (Cuba activos, mujeres, juveniles), `chess.capablanca` y `chess.elite-broadcasts` (eventos) | |
| 8 | Boxeo / UFC | `boxing.wbc` y `mma.ufc` → `rankings/` (una división por archivo) | Récord en `stats` (`W`, `L`, `D`, `KO`); campeón con `rank: 0` y `extra.champion`. |

## Reglas para la app

- Ignorar campos desconocidos y no fallar si falta uno opcional (`schemaVersion` 1).
- Las claves de `stats` se traducen con `sports.json → stats`; si no hay etiqueta, mostrar la clave.
- `status.json` dice por fuente cuándo se actualizó por última vez; mostrar "Actualizado hace X".
