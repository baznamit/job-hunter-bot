from research.loader import load_registry
from research.validator import validate_registry


def main() -> None:
    registry = load_registry()

    validate_registry(registry)

    print(
        f"Successfully validated {len(registry.companies)} companies."
    )


if __name__ == "__main__":
    main()