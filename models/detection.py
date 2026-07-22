from pydantic import BaseModel, ConfigDict, Field

from .company import ProviderType


class DetectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str

    # ATS-specific slug extracted from the page (e.g. Greenhouse board name).
    # Feeds directly into Company.provider.config during registry mapping.
    identifier: str | None = None