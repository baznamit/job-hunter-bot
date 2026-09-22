def main() -> None:
    print(
        "[BATCH-PROBE] "
        "Starting unresolved company batch"
    )

    _run(
        "Capgemini",
        probe_capgemini,
    )

    _run(
        "LTIMindtree / LTM",
        probe_ltm,
    )

    _run(
        "CleverTap",
        probe_clevertap,
    )

    print()
    print(
        "[BATCH-PROBE] Finished"
    )


if __name__ == "__main__":
    main()