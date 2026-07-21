import json

from models import CompanyRegistry

from .paths import COMPANIES_FILE


class RegistryLoader:
    """
    Responsible for loading the company registry.
    """

    @staticmethod
    def load() -> CompanyRegistry:
        with COMPANIES_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            return CompanyRegistry.model_validate_json(
                json.dumps(json.load(file))
            )