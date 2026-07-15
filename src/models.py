from dataclasses import dataclass


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: str