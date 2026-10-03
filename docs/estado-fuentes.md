# Estado de las fuentes (verificado el 2026-10-03)

| Competición | Fuente | Qué se obtiene | Observaciones |
|---|---|---|---|
| Serie Nacional (SNB) | beisbolcubano.cu (HTML) | clasificación, plantillas por equipo con fecha de nacimiento y foto, director técnico | Solo expone la serie en curso. Al 03-10-2026 la tabla de la nueva serie está vacía (no ha comenzado); el parser se probó con la página archivada de febrero 2026. |
| MLB, LIDOM, LVBP, LMP, LBPRC, Serie del Caribe, LMB | statsapi.mlb.com (JSON) | equipos, clasificación, plantillas (40 hombres / activos), coaches, país de nacimiento, logos SVG, fotos | Las plantillas de invierno 2026-27 aún no están publicadas (0 jugadores); se rellenan solas cuando la fuente las publique. Logos de liga en mlbstatic: existen para 1, 103, 104, 125 y 131; dan 404 para 132, 133, 135 y 162. |
| NPB (Japón) | npb.jp/bis/eng (HTML) | clasificación (Central y Pacífico), plantillas con mánager | Sin nacionalidad: los cubanos se identifican con Wikidata (P4260). El formato de temporadas pasadas es distinto (tablas anidadas); el parser admite ambos. |
| KBO (Corea) | eng.koreabaseball.com (HTML) | clasificación | Plantillas pendientes. |
| Liga colombiana | lpbcol (HTML) | clasificación | La página no indica la temporada; se emite un aviso en cada ejecución. |
| Probeis (Panamá) | probeis.com | — | Desactivada: el DNS no resuelve desde los runners. |
| Fútbol (20 ligas + 5 copas) | site.api.espn.com / sports.core.api.espn.com (JSON) | equipos, clasificación, plantillas, logos, ciudadanía | En copas (`rosters: false`) no se piden plantillas: se toman de la liga del club para no sobrescribirlas. Ecuador 2026 no tiene clasificación en ESPN. La lista de entrenadores de ESPN es histórica y no se usa. |
| SuperLega (voleibol) | legavolley.it (HTML) | clasificación (`?Anno=`), plantillas, staff, logos | Los cambios de patrocinador crean nombres nuevos; se fusionan en `state/overrides.json`. Algunos logos de equipo son JPEG vacíos de 2×2 px; se usa el logo de la sociedad. |
| UFC | ufc.com (HTML) | rankings por división y libra por libra, ficha del atleta (lugar de nacimiento, récord, foto) | Los rankings de ESPN para MMA están desactualizados, por eso se usa la página oficial. |
| Boxeo WBC | wbcboxing.com (HTML) | 18 divisiones masculinas y 16 femeninas, 40 clasificados cada una, campeón, nacionalidad | Fecha "Updated" de la página se publica como `asOf`. |
| Ajedrez FIDE | ratings.fide.com | Top 100 (open, mujeres, juveniles, niñas) y lista completa XML mensual (~14 MB) filtrada por federación CUB | La lista completa se descarga una vez al mes (`refresh: monthly`). |
| Capablanca in Memoriam | chess-results.com | clasificación con ID FIDE | Torneo 2026: tnr1433961. Para años futuros, añadir el nuevo tnr en `config/competitions.yml`. |
| Torneos élite | lichess.org/api/broadcast | eventos de nivel ≥ 4, jugadores, fotos con crédito | Lichess responde 429 con facilidad: el pipeline se detiene y continúa en la siguiente ejecución. |
| Cubanos (enriquecimiento) | query.wikidata.org | ciudadanía (P27) y lugar de nacimiento (P19) por ID externo | Propiedades: P3541 MLB, P4260 NPB, P3681 ESPN FC, P9722 UFC, P1440 FIDE, P4303 Legavolley. |
| Fotos alternativas | Wikidata P18 + commons.wikimedia.org | foto, autor y licencia | Wikimedia exige un User-Agent con contacto: definir la variable `PIPELINE_CONTACT`. Si responde 429, se continúa en la siguiente ejecución. |

## Resultado de la ejecución completa del 2026-10-03

- 44 competiciones configuradas (43 activas), 0 fuentes con error.
- `build`: 3 242 archivos públicos, 575 equipos, 27 144 personas, 1 519 cubanos
  (202 en béisbol fuera de Cuba, 22 en boxeo, 7 en ajedrez fuera de Cuba, 2 en voleibol).
- Logos: 583 de 588 procesados; faltan los de liga sin fuente oficial (LMP, LVBP,
  LBPRC, Serie del Caribe) y un equipo invitado de la Serie del Caribe.
- Fotos: se resuelven por lotes (primero los cubanos); en GitHub Actions el lote
  diario es de 1 200 (unos 3 minutos por cada 100 fotos).
