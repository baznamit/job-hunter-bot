from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .company import Company


class CompanyRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    companies: list[Company]


class RegistryCache(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    generated_at: datetime | None = None
    companies: dict = Field(default_factory=dict)