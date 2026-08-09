"""Persistence and compatibility adapters."""

from ifem.infrastructure.legacy_project import (
    legacy_config_from_project,
    project_from_legacy_config,
)
from ifem.infrastructure.project_io import load_project, save_project
from ifem.infrastructure.project_library import (
    PROJECT_EXTENSION,
    ProjectLibrary,
    ProjectLibraryEntry,
    default_project_library_root,
    normalize_project_name,
)

__all__ = [
    "legacy_config_from_project",
    "project_from_legacy_config",
    "load_project",
    "save_project",
    "PROJECT_EXTENSION",
    "ProjectLibrary",
    "ProjectLibraryEntry",
    "default_project_library_root",
    "normalize_project_name",
]
