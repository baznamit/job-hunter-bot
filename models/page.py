from pydantic import BaseModel, ConfigDict


class PageSnapshot(BaseModel):
    """
    Represents the result of fetching a web page.
    """

    model_config = ConfigDict(extra="forbid")

    original_url: str
    final_url: str
    status_code: int
    html: str
    headers: dict[str, str]