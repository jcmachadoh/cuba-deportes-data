"""Utilidades: slugs, normalización de nombres, fechas y países."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any

# --------------------------------------------------------------------- texto

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def slugify(s: str, max_len: int = 60) -> str:
    s = strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:max_len].strip("-") or "x"


def norm_name(s: str) -> str:
    """Clave de comparación de nombres: sin tildes, minúsculas, tokens ordenados."""
    toks = re.findall(r"[a-z0-9]+", strip_accents(s or "").lower())
    return " ".join(sorted(toks))


def clean(s: Any) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s or None


def to_int(v: Any) -> int | None:
    if isinstance(v, float):
        return int(v) if v.is_integer() else None
    try:
        s = str(v).replace(",", "").strip()
        return int(float(s)) if s.endswith(".0") else int(s)
    except (TypeError, ValueError):
        return None


def to_float(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    if s in ("", "-", "--", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> date:
    return datetime.now(timezone.utc).date()


def natural_name(s: str) -> str:
    """'CARMONA CASANOVA Guillermo Rolando' -> 'Guillermo Rolando Carmona Casanova'."""
    toks = s.split()
    up = []
    for t in toks:
        if t.isupper() and len(t) > 1:
            up.append(t)
        else:
            break
    if up and len(up) < len(toks):
        rest = toks[len(up):]
        return " ".join(rest + [w.lower() if w in ("DE", "DEL", "LA", "LOS", "LAS", "Y") else w.capitalize() for w in up])
    return s


# --------------------------------------------------------------------- fechas
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(s: str | None) -> str | None:
    """Devuelve YYYY-MM-DD a partir de formatos comunes (ISO, dd/mm/yyyy, 'Mar. 20, 1979')."""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    m = re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})", s)
    if m and m[1].lower() in _MONTHS:
        return f"{m[3]}-{_MONTHS[m[1].lower()]:02d}-{int(m[2]):02d}"
    return None


# --------------------------------------------------------------------- países
# Nombre (como lo escriben MLB/ESPN/WBC/FIDE) -> ISO 3166-1 alfa-2.
_COUNTRY = {
    "cuba": "CU", "cub": "CU",
    "usa": "US", "united states": "US", "estados unidos": "US",
    "dominican republic": "DO", "republica dominicana": "DO", "dom": "DO",
    "venezuela": "VE", "ven": "VE",
    "mexico": "MX", "mex": "MX",
    "puerto rico": "PR", "pur": "PR",
    "colombia": "CO", "col": "CO",
    "panama": "PA", "pan": "PA",
    "nicaragua": "NI", "curacao": "CW", "aruba": "AW", "bahamas": "BS",
    "canada": "CA", "can": "CA",
    "japan": "JP", "jpn": "JP", "south korea": "KR", "korea": "KR", "kor": "KR",
    "taiwan": "TW", "australia": "AU", "netherlands": "NL", "ned": "NL",
    "brazil": "BR", "bra": "BR", "argentina": "AR", "arg": "AR", "chile": "CL", "chi": "CL",
    "peru": "PE", "uruguay": "UY", "ecuador": "EC", "paraguay": "PY", "bolivia": "BO",
    "spain": "ES", "esp": "ES", "italy": "IT", "ita": "IT", "france": "FR", "fra": "FR",
    "germany": "DE", "ger": "DE", "portugal": "PT", "por": "PT", "england": "GB",
    "great britain": "GB", "united kingdom": "GB", "gb": "GB", "scotland": "GB", "wales": "GB",
    "ireland": "IE", "belgium": "BE", "turkey": "TR", "turkiye": "TR", "poland": "PL",
    "ukraine": "UA", "russia": "RU", "kazakhstan": "KZ", "uzbekistan": "UZ",
    "philippines": "PH", "morocco": "MA", "south africa": "ZA", "nigeria": "NG",
    "china": "CN", "india": "IN", "norway": "NO", "nor": "NO", "iran": "IR",
    "azerbaijan": "AZ", "armenia": "AM", "hungary": "HU", "czech republic": "CZ",
    "serbia": "RS", "croatia": "HR", "georgia": "GE", "sweden": "SE", "denmark": "DK",
    "mongolia": "MN", "thailand": "TH", "ghana": "GH", "costa rica": "CR",
    "honduras": "HN", "guatemala": "GT", "el salvador": "SV", "jamaica": "JM",
    "kosovo": "XK", "ivory coast": "CI", "cote d'ivoire": "CI", "bosnia-herzegovina": "BA",
    "bosnia and herzegovina": "BA", "dr congo": "CD", "congo dr": "CD", "cape verde": "CV",
    "north macedonia": "MK", "czechia": "CZ", "republic of ireland": "IE", "northern ireland": "GB",
    "usa ": "US", "u.s.a.": "US", "korea, south": "KR", "taipei": "TW", "chinese taipei": "TW",
    "haiti": "HT", "trinidad and tobago": "TT", "new zealand": "NZ",
}

# FIDE / IOC (alfa-3) -> alfa-2 (los más frecuentes en los rankings)
_IOC = {
    "CUB": "CU", "USA": "US", "NOR": "NO", "IND": "IN", "CHN": "CN", "UZB": "UZ", "NED": "NL",
    "FRA": "FR", "GER": "DE", "ESP": "ES", "ITA": "IT", "RUS": "RU", "FID": "XX", "AZE": "AZ",
    "ARM": "AM", "HUN": "HU", "POL": "PL", "UKR": "UA", "ENG": "GB", "IRI": "IR", "ROU": "RO",
    "CZE": "CZ", "SRB": "RS", "TUR": "TR", "GEO": "GE", "KAZ": "KZ", "PER": "PE", "ARG": "AR",
    "BRA": "BR", "MEX": "MX", "CAN": "CA", "VIE": "VN", "PHI": "PH", "ISR": "IL", "SWE": "SE",
    "DEN": "DK", "SUI": "CH", "AUT": "AT", "BEL": "BE", "GRE": "GR", "BUL": "BG", "CRO": "HR",
    "SLO": "SI", "SVK": "SK", "LTU": "LT", "LAT": "LV", "EST": "EE", "FIN": "FI", "ISL": "IS",
    "MGL": "MN", "KOR": "KR", "JPN": "JP", "COL": "CO", "VEN": "VE", "CHI": "CL", "ECU": "EC",
    "DOM": "DO", "PUR": "PR", "PAN": "PA", "URU": "UY", "PAR": "PY", "BOL": "BO", "AUS": "AU",
    "SCO": "GB", "WLS": "GB", "IRL": "IE", "POR": "PT", "EGY": "EG", "RSA": "ZA", "BLR": "BY",
    "MDA": "MD", "MNE": "ME", "BIH": "BA", "MKD": "MK", "ALB": "AL", "KGZ": "KG", "TKM": "TM",
    "BAN": "BD", "INA": "ID", "SGP": "SG", "MAS": "MY", "UAE": "AE", "QAT": "QA",
}


def country_code(name: str | None) -> str | None:
    """Convierte nombre o código de país a ISO alfa-2. Devuelve None si no se conoce."""
    if not name:
        return None
    raw = strip_accents(str(name)).strip()
    raw = re.sub(r"[\U0001F1E6-\U0001F1FF]", "", raw).strip()  # quita banderas emoji
    if len(raw) == 3 and raw.upper() in _IOC:
        return _IOC[raw.upper()]
    if len(raw) == 2 and raw.isalpha() and raw.isupper():
        return raw
    if raw.lower() in _COUNTRY:
        return _COUNTRY[raw.lower()]
    return _pycountry(raw)


def _pycountry(raw: str) -> str | None:
    try:
        import pycountry
    except ImportError:  # pragma: no cover
        return None
    try:
        c = pycountry.countries.lookup(raw)
        return c.alpha_2
    except LookupError:
        return None   # sin búsqueda difusa: preferimos None a un país equivocado


def countries_from_text(s: str | None) -> list[str]:
    """'🇰🇿 Kazakhstan / 🇺🇸 United States' -> ['KZ','US']"""
    out: list[str] = []
    for part in re.split(r"[/,]", s or ""):
        c = country_code(part)
        if c and c not in out:
            out.append(c)
    return out
