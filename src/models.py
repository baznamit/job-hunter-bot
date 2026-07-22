# This file is a compatibility shim.
# The canonical Job model is models.Job (pydantic) in models/job.py.
# Import from there directly; this shim will be removed in Phase 3.
from models import Job  # noqa: F401

__all__ = ["Job"]
