"""Core application packages for the iFEM reconstruction software."""

from ifem.application.analysis_service import (
    DEFAULT_ALGORITHM_ID,
    AnalysisService,
    create_default_analysis_service,
    get_default_analysis_service,
)

__all__ = [
    "DEFAULT_ALGORITHM_ID",
    "AnalysisService",
    "create_default_analysis_service",
    "get_default_analysis_service",
]
