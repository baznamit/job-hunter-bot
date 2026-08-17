from research.loader import load_registry
from research.validator import validate_registry


def test_registry_is_valid():
    registry = load_registry()

    validate_registry(registry)