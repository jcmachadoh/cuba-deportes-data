"""Rutas del repositorio. Se pueden sobreescribir con variables de entorno
(útil en tests)."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("PIPELINE_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = ROOT / "config"
SCHEMA_DIR = ROOT / "schemas" / "v1"
DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", ROOT / "data" / "v1"))   # datos canónicos (se versionan en git)
STATE_DIR = Path(os.environ.get("PIPELINE_STATE_DIR", ROOT / "state"))        # registro de IDs, estado de imágenes
PUBLIC_DIR = Path(os.environ.get("PIPELINE_PUBLIC_DIR", ROOT / "public"))     # salida para Cloudflare (no se versiona)
R2_DIR = Path(os.environ.get("PIPELINE_R2_DIR", ROOT / "public_r2"))          # salida para R2 (fotos de Commons)
CACHE_DIR = Path(os.environ.get("PIPELINE_CACHE_DIR", ROOT / ".cache" / "http"))
