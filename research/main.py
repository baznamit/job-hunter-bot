from research.loader import RegistryLoader
from research.validator import RegistryValidator


def main() -> None:
    registry = RegistryLoader.load()

    RegistryValidator.validate(registry)

    print(
        f"Successfully validated "
        f"{len(registry.companies)} companies."
    )


if __name__ == "__main__":
    main()