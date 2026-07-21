from research.loader import RegistryLoader


def main() -> None:

    registry = RegistryLoader.load()

    print(
        f"Successfully loaded "
        f"{len(registry.companies)} companies."
    )


if __name__ == "__main__":
    main()