# Modelo de datos

Dos capas:

- `data/v1/` (en git): datos normalizados, sin hidratar, una entidad por archivo.
  Se escribe solo si el contenido cambió (ignorando `updatedAt`), así los commits
  muestran cambios reales y el historial de git sirve de histórico.
- `public/v1/` (no está en git, lo genera `build`): lo que consume la app. Igual
  estructura pero con referencias hidratadas (nombre, logo, foto) para que cada
  pantalla necesite un solo archivo.

## Principios de flexibilidad

1. **IDs canónicos propios**, nunca los de la fuente: equipos `{sport}.{slug}`,
   personas `p.{slug}.{añoNacimiento}` (sufijo `-2`, `-3` si hay colisión).
   `state/registry.json` mapea `fuente:idExterno → idCanónico`; si una fuente
   cambia el nombre, el ID no cambia. `externalIds` guarda todos los IDs externos
   (MLB, ESPN, FIDE, Wikidata…) para cruzar fuentes.
2. **Sobrescrituras manuales** en `state/overrides.json`
   (`{"team": {"legavolley-name:xxx": "volleyball.yyy"}}`) para fusionar equipos
   que cambian de patrocinador o personas duplicadas.
3. **Envoltorio común**: todos los archivos tienen `schemaVersion`, `type`, `id`,
   `updatedAt`, `sources`. Campos nuevos se añaden sin romper; quitar o renombrar
   un campo exige `v2/` en paralelo.
4. **Estadísticas como mapa** `stats: {clave: valor}`. Cada deporte declara sus
   claves y etiquetas en `config/sports.yml`, así añadir una columna no cambia el
   esquema. Lo que no es estadística va en `extra`.
5. **Participante genérico** en clasificaciones y rankings: `participantType`
   `team` o `person`, de modo que el mismo formato sirve para ligas, UFC, boxeo y
   ajedrez.
6. **Temporada como etiqueta** (`2026` o `2026-27`) definida por competición
   (`season.format`, `start_month`). Todo lo que depende de la temporada cuelga de
   `seasons/{s}/`.
7. **Plantillas por grupos** (`groups[].code` = P, C, IF, OF, DH, STAFF en béisbol;
   GK, DF, MF, FW en fútbol; etc.) con mapeo posición → grupo en
   `config/sports.yml`.
8. **Nacionalidad con evidencia**: `nationalities` (ISO-3166 alfa-2, sin incluir
   automáticamente el país de nacimiento), `birthCountry`, `isCuban` y
   `cubanEvidence` (p. ej. `beisbolcubano.snb`, `mlb.birthCountry`,
   `fide.federation`, `wikidata.P27`).
9. **Imágenes desacopladas**: los adaptadores solo proponen candidatos
   (`state/candidates/`); `logos` y `photos` deciden y guardan el resultado en
   `state/media/`. Se puede cambiar de fuente de imágenes sin tocar los datos.

## Estructura

```
data/v1/
  competitions/{competitionId}.json
  competitions/{competitionId}/seasons/{s}/standings.json
  competitions/{competitionId}/seasons/{s}/teams.json
  competitions/{competitionId}/seasons/{s}/rankings/{rankingId}.json
  competitions/{competitionId}/seasons/{s}/events/{eventId}.json
  teams/{teamId}.json
  teams/{teamId}/seasons/{s}/roster.json
  persons/{00..ff}.json            # 256 shards por sha1(personId)[:2]
data/media/logos/{hash16}-{256|64}.webp
state/
  registry.json  overrides.json  status.json
  candidates/{logos,photos}.json
  media/{logos,photos,placeholders}.json
public/                            # salida de build (desplegada)
  _headers
  media/logos/...  media/packs/logos-{sport}-{hash}.zip
  v1/... + sports.json, cubanos/index.json, media.json, manifest.json, status.json
```

Esquemas JSON (draft 2020-12) en `schemas/v1/`; `tests/test_schemas.py` valida
una muestra de `data/v1` en cada ejecución de pruebas.

## Límites respetados

- Cloudflare Workers Static Assets (plan Free): máx. 20 000 archivos y 25 MiB por
  archivo; `build` falla si se superan 19 000 archivos.
- GitHub Actions: repositorio público = minutos gratuitos sin límite; cada job
  dura como máximo 6 h (el pipeline usa `timeout-minutes: 90`).
