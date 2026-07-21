from enum import Enum

from pydantic import BaseModel, ConfigDict


class ProviderType(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKDAY = "workday"
    SMARTRECRUITERS = "smartrecruiters"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class DetectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderType
    confidence: float
    reason: str