from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl


class Job(BaseModel):
    """
    A normalized representation of a job posting, independent of the ATS.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    company: str
    location: str
    url: HttpUrl

    posted_at: datetime | None = None
    department: str | None = None
    employment_type: str | None = None
    remote: bool = False