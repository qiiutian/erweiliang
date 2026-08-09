from __future__ import annotations

import json
from pathlib import Path

from ifem.domain.project import ProjectDocument


def save_project(path, project: ProjectDocument) -> Path:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            project.to_dict(),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def load_project(path) -> ProjectDocument:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"项目文件解析失败：{exc.msg}（第 {exc.lineno} 行，第 {exc.colno} 列）"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("项目文件根节点必须是对象。")
    return ProjectDocument.from_dict(payload)
