from models import CompanyRegistry


class RegistryValidator:
    """
    Performs business validation on a company registry.
    """

    @staticmethod
    def validate(registry: CompanyRegistry) -> None:
        RegistryValidator._validate_unique_ids(registry)
        RegistryValidator._validate_unique_names(registry)
        RegistryValidator._validate_unique_career_pages(registry)

    @staticmethod
    def _validate_unique_ids(registry: CompanyRegistry) -> None:
        ids = [company.id for company in registry.companies]

        duplicates = {
            company_id
            for company_id in ids
            if ids.count(company_id) > 1
        }

        if duplicates:
            raise ValueError(
                f"Duplicate company IDs found: {sorted(duplicates)}"
            )

    @staticmethod
    def _validate_unique_names(registry: CompanyRegistry) -> None:
        names = [company.name.lower() for company in registry.companies]

        duplicates = {
            name
            for name in names
            if names.count(name) > 1
        }

        if duplicates:
            raise ValueError(
                f"Duplicate company names found: {sorted(duplicates)}"
            )

    @staticmethod
    def _validate_unique_career_pages(registry: CompanyRegistry) -> None:
        urls = [str(company.career_page) for company in registry.companies]

        duplicates = {
            url
            for url in urls
            if urls.count(url) > 1
        }

        if duplicates:
            raise ValueError(
                f"Duplicate career pages found: {sorted(duplicates)}"
            )