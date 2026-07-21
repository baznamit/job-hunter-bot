from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

COMPANIES_FILE = CONFIG_DIR / "companies.json"
REGISTRY_CACHE_FILE = DATA_DIR / "registry_cache.json"