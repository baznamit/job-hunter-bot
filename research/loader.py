import json

from models import CompanyRegistry

from .paths import COMPANIES_FILE


def load_registry() -> CompanyRegistry:
    """
    Load and validate the company registry from disk.
    """
    with COMPANIES_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return CompanyRegistry.model_validate(data)