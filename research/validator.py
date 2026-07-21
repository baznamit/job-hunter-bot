from collections import Counter

from models import CompanyRegistry


def validate_registry(registry: CompanyRegistry) -> None:
    """
    Perform business validation on the company registry.
    """
    _validate_unique_ids(registry)
    _validate_unique_names(registry)
    _validate_unique_career_pages(registry)


def _validate_unique_ids(registry: CompanyRegistry) -> None:
    ids = [company.id for company in registry.companies]
    duplicates = [
        company_id
        for company_id, count in Counter(ids).items()
        if count > 1
    ]

    if duplicates:
        raise ValueError(f"Duplicate company IDs: {duplicates}")


def _validate_unique_names(registry: CompanyRegistry) -> None:
    names = [company.name.lower() for company in registry.companies]
    duplicates = [
        name
        for name, count in Counter(names).items()
        if count > 1
    ]

    if duplicates:
        raise ValueError(f"Duplicate company names: {duplicates}")


def _validate_unique_career_pages(registry: CompanyRegistry) -> None:
    urls = [str(company.career_page) for company in registry.companies]
    duplicates = [
        url
        for url, count in Counter(urls).items()
        if count > 1
    ]

    if duplicates:
        raise ValueError(f"Duplicate career pages: {duplicates}")