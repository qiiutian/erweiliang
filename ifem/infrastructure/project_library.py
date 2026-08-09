"""Managed project-library paths and lightweight project metadata."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ifem.infrastructure.project_io import load_project


PROJECT_EXTENSION = ".ifemproj"
PROJECT_LIBRARY_ENV = "IFEM_PROJECTS_DIR"
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def default_project_library_root() -> Path:
    override = os.environ.get(PROJECT_LIBRARY_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / "Documents" / "iFEM" / "Projects").resolve()


def normalize_project_name(value: str) -> str:
    name = str(value or "").strip()
    if name.lower().endswith(PROJECT_EXTENSION):
        name = name[: -len(PROJECT_EXTENSION)].strip()
    if not name:
        raise ValueError("请输入项目名称。")
    if len(name) > 80:
        raise ValueError("项目名称不能超过 80 个字符。")
    if name in {".", ".."} or name.endswith((".", " ")):
        raise ValueError("项目名称不能以句点或空格结尾。")
    if _INVALID_NAME.search(name):
        raise ValueError('项目名称不能包含 < > : " / \\ | ? * 等字符。')
    if name.upper() in _RESERVED_NAMES:
        raise ValueError("该名称为系统保留名称，请使用其他名称。")
    return name


@dataclass(frozen=True)
class ProjectLibraryEntry:
    name: str
    path: Path
    modified_at: float
    modeling_space: str = ""
    node_count: int = 0
    element_count: int = 0
    sensor_count: int = 0
    valid: bool = True
    error: str = ""


class ProjectLibrary:
    """A single managed directory containing user-visible iFEM projects."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or default_project_library_root()).expanduser().resolve()

    def ensure_root(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def path_for_name(self, name: str) -> Path:
        normalized = normalize_project_name(name)
        return self.root / f"{normalized}{PROJECT_EXTENSION}"

    def contains_name(self, name: str) -> bool:
        return self.path_for_name(name).exists()

    def contains_path(self, path: str | Path | None) -> bool:
        if path is None:
            return False
        candidate = Path(path).expanduser().resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return False
        return True

    def entries(self) -> tuple[ProjectLibraryEntry, ...]:
        root = self.ensure_root()
        entries = []
        for path in root.glob(f"*{PROJECT_EXTENSION}"):
            try:
                modified_at = path.stat().st_mtime
            except OSError:
                continue
            try:
                project = load_project(path)
                entry = ProjectLibraryEntry(
                    name=project.name,
                    path=path,
                    modified_at=modified_at,
                    modeling_space=project.modeling_space,
                    node_count=len(project.nodes),
                    element_count=len(project.elements),
                    sensor_count=len(project.sensors),
                )
            except (KeyError, OSError, TypeError, ValueError) as exc:
                entry = ProjectLibraryEntry(
                    name=path.stem,
                    path=path,
                    modified_at=modified_at,
                    valid=False,
                    error=str(exc),
                )
            entries.append(entry)
        return tuple(
            sorted(
                entries,
                key=lambda entry: (-entry.modified_at, entry.name.casefold()),
            )
        )


__all__ = [
    "PROJECT_EXTENSION",
    "PROJECT_LIBRARY_ENV",
    "ProjectLibrary",
    "ProjectLibraryEntry",
    "default_project_library_root",
    "normalize_project_name",
]
