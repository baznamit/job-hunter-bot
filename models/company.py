from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class CompanyCategory(str, Enum):
    FINTECH = "FinTech"
    SAAS = "SaaS"
    AI = "AI"
    BANKING = "Banking"
    PAYMENTS = "Payments"
    ECOMMERCE = "E-Commerce"
    PRODUCT = "Product"
    DEVELOPER_TOOLS = "Developer Tools"


class ProviderType(str, Enum):
    UNKNOWN = "unknown"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    ASHBY = "ashby"
    SMARTRECRUITERS = "smartrecruiters"
    CUSTOM = "custom"


class ProviderStatus(str, Enum):
    RESEARCH_PENDING = "research_pending"
    PARTIAL = "partial"
    VERIFIED = "verified"
    IMPLEMENTED = "implemented"
    TESTED = "tested"


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    board: str | None = None
    tenant: str | None = None
    organization: str | None = None


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ProviderType = ProviderType.UNKNOWN
    status: ProviderStatus = ProviderStatus.RESEARCH_PENDING
    config: ProviderConfig = Field(default_factory=ProviderConfig)


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: CompanyCategory
    priority: int = Field(ge=1, le=3)
    enabled: bool = True

    career_page: HttpUrl

    provider: Provider = Field(default_factory=Provider)

    locations: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)

    supports_remote: bool = False

    notes: str = ""