from pydantic import BaseModel, Field

from .company import ProviderType


class DetectionResult(BaseModel):
    provider: ProviderType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    identifier: str | None = None

    # Structured provider configuration.
    #
    # Greenhouse / Lever:
    #   {"board": "..."}
    #
    # Ashby:
    #   {"organization": "..."}
    #
    # Workday:
    #   {
    #       "tenant": "...",
    #       "cluster": "wd5",
    #       "board": "..."
    #   }
    config: dict[str, str] = Field(default_factory=dict)