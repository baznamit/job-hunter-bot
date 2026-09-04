from dataclasses import dataclass, field

from models import Job


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

    elapsed_seconds: float = 0.0

    success: bool = True
    skipped: bool = False
    error: str | None = None
