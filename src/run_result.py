from dataclasses import dataclass, field

from models import Job
from src.filters import FilterDiagnostics


@dataclass
class CompanyRunResult:
    company_id: str
    company_name: str
    provider: str

    jobs_fetched: int = 0
    matching: list[Job] = field(
        default_factory=list
    )

    direct_count: int = 0
    promoted_count: int = 0
    filter_diagnostics: FilterDiagnostics | None = None

    elapsed_seconds: float = 0.0

    success: bool = True
    skipped: bool = False
    error: str | None = None

    # Fetch/enrichment coverage is per result, never stored on a shared
    # adapter instance.  Non-Workday providers retain the complete default.
    coverage_status: str = "complete"
    listing_status: str = "complete"
    enrichment_candidates: int = 0
    enrichment_attempted: int = 0
    enrichment_resolved: int = 0
    enrichment_unresolved: int = 0
    enrichment_unstarted: int = 0
    # Tracked Workday normal-fetch requests only; not a global HTTP total.
    http_attempts: int = 0
    http_retries: int = 0
    http_429_responses_by_stage: dict[str, int] = field(default_factory=dict)
    http_429_hosts: set[str] = field(default_factory=set)
    deferred: int = 0
    deferred_before_attempt: int = 0
    deferred_after_attempt: int = 0
    deferral_reasons: dict[str, int] = field(default_factory=dict)
    failure_reasons: dict[str, int] = field(default_factory=dict)
    coverage_note: str | None = None
    unique_matching_urls: int = 0
    seen_urls: int = 0
    new_unique_urls: int = 0
    duplicate_suppressed_urls: int = 0
    duplicate_matching_records: int = 0
    cross_company_duplicate_urls: int = 0
