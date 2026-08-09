"""Application services coordinating projects and algorithms."""

from ifem.application.algorithm_matching import (
    AlgorithmMatch,
    ModelFeatureProfile,
    match_project_algorithms,
    profile_project,
)
from ifem.application.analysis_service import (
    DEFAULT_ALGORITHM_ID,
    AlgorithmRegistry,
    AlgorithmValidationError,
    AnalysisService,
    create_default_analysis_service,
    get_default_analysis_service,
)

__all__ = [
    "AlgorithmMatch",
    "ModelFeatureProfile",
    "match_project_algorithms",
    "profile_project",
    "DEFAULT_ALGORITHM_ID",
    "AlgorithmRegistry",
    "AlgorithmValidationError",
    "AnalysisService",
    "create_default_analysis_service",
    "get_default_analysis_service",
]
