"""Enriquecimiento con Wikidata (CC0): detección de cubanos y datos faltantes.

Varias fuentes (NPB, KBO, ufc.com, legavolley) no publican nacionalidad, y
muchos cubanos compiten con otra federación/nacionalidad deportiva. Wikidata
enlaza a la persona con el ID de cada fuente, así que se pregunta:

  "personas con <ID de la fuente> cuya ciudadanía es Cuba (P27=Q241)
   o cuyo lugar de nacimiento está en Cuba (P19/P17=Q241)"

y se cruzan con el registro de IDs. Cada coincidencia queda con su evidencia
(p. ej. "wikidata.P27") para que la app pueda mostrar por qué es "cubano".
"""
from __future__ import annotations

import logging
from typing import Any

from .core.http import Http
from .core.ids import IdRegistry
from .core.store import Store

log = logging.getLogger("enrich")
SPARQL = "https://query.wikidata.org/sparql"
# propiedad de Wikidata -> prefijo de fuente en state/registry.json
PROPS = {
    "P3541": "mlb",          # MLB.com player ID
    "P4260": "npb",          # NPB player ID
    "P3681": "espn",         # ESPN FC player ID (fútbol)
    "P9722": "ufc",          # UFC athlete ID (slug)
    "P1440": "fide",         # FIDE player ID
    "P4303": "legavolley",   # Lega Pallavolo Serie A player ID
}
Q_CUBANS = """SELECT ?item ?ext ?how ?img WHERE {
  ?item wdt:%(p)s ?ext .
  { ?item wdt:P27 wd:Q241 . BIND("P27" AS ?how) }
  UNION
  { ?item wdt:P19/wdt:P17 wd:Q241 . BIND("P19" AS ?how) }
  OPTIONAL { ?item wdt:P18 ?img }
}"""


def sparql(http: Http, query: str) -> list[dict[str, Any]]:
    data = http.json(SPARQL, params={"query": query, "format": "json"},
                     headers={"Accept": "application/sparql-results+json"}, use_cache=False)
    return [{k: v["value"] for k, v in row.items()} for row in data["results"]["bindings"]]


def run() -> int:
    http, ids, store = Http(), IdRegistry(), Store()
    total = 0
    for prop, source in PROPS.items():
        try:
            rows = sparql(http, Q_CUBANS % {"p": prop})
        except Exception as e:  # noqa: BLE001
            log.error("Wikidata %s falló: %s", prop, e)
            continue
        hits = 0
        for r in rows:
            pid = ids.lookup("person", source, r["ext"])
            if not pid or not store.get_person(pid):
                continue
            qid = r["item"].rsplit("/", 1)[-1]
            doc = {"id": pid, "isCuban": True, "cubanEvidence": [f"wikidata.{r['how']}"],
                   "externalIds": {"wikidata": qid}}
            if r["how"] == "P27":
                doc["nationalities"] = ["CU"]
            store.upsert_person(doc)
            if r.get("img"):
                store.add_candidates("photos", pid, [{"type": "commons", "value": r["img"], "source": "wikidata", "priority": 40}])
            hits += 1
        log.info("%s (%s): %d cubanos en Wikidata, %d presentes en nuestros datos", prop, source, len(rows), hits)
        total += hits
    store.flush()
    store.flush_candidates()
    log.info("enriquecidas %d personas", total)
    return 0
