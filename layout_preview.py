from __future__ import annotations

from typing import Any


TOP_SURFACE_NAMES = {"top", "upper", "up", "上", "上表面"}
BOTTOM_SURFACE_NAMES = {"bot", "bottom", "lower", "down", "下", "下表面"}


def build_measurement_preview(node_x_text: str, measurement_rows: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        node_x = _parse_node_x(node_x_text)
    except ValueError as exc:
        return _empty_preview(str(exc))

    if not measurement_rows:
        return _empty_preview("填写合法节点与测量数据后显示示意。")

    items = _build_items(node_x, measurement_rows)
    if not items:
        return _empty_preview("填写至少一条合法测点后显示示意。")

    beam_start = node_x[0]
    beam_end = node_x[-1]
    return {
        "ok": True,
        "message": "",
        "beam_start": beam_start,
        "beam_end": beam_end,
        "beam_length": beam_end - beam_start,
        "nodes": node_x,
        "items": items,
        "measurement_count": len(items),
        "node_count": len(node_x),
    }


def _empty_preview(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "message": message,
        "beam_start": 0.0,
        "beam_end": 0.0,
        "beam_length": 0.0,
        "nodes": [],
        "items": [],
        "measurement_count": 0,
        "node_count": 0,
    }


def _parse_node_x(node_x_text: str) -> list[float]:
    text = str(node_x_text or "").strip()
    if not text:
        raise ValueError("填写合法节点与测量数据后显示示意。")

    values = []
    for part in text.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError as exc:
            raise ValueError("节点 x 坐标存在无法解析的数值。") from exc

    if len(values) < 2:
        raise ValueError("节点 x 坐标至少需要两个递增节点。")

    if any(values[idx + 1] <= values[idx] for idx in range(len(values) - 1)):
        raise ValueError("节点 x 坐标必须严格递增。")

    return values


def _build_items(node_x: list[float], measurement_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n_elems = len(node_x) - 1
    items = []

    for index, row in enumerate(measurement_rows, start=1):
        element = _try_parse_int(row.get("element"))
        if element is None or element < 0 or element >= n_elems:
            continue

        element_start = node_x[element]
        element_end = node_x[element + 1]
        element_length = element_end - element_start

        x_loc = _try_parse_float(row.get("x"))
        if x_loc is None or x_loc < 0.0 or x_loc > element_length:
            continue

        surface_side = _try_resolve_surface_side(row)
        if surface_side is None:
            continue

        items.append(
            {
                "sequence": index,
                "element_index": element,
                "local_x": x_loc,
                "global_x": element_start + x_loc,
                "surface_side": surface_side,
                "surface_label": "上表面" if surface_side == "top" else "下表面",
                "strain_text": _format_strain(row.get("strain")),
            }
        )

    return items


def _parse_float(value: Any, message: str) -> float:
    text = str(value if value is not None else "").strip()
    if not text:
        raise ValueError(message)
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(message) from exc


def _parse_int(value: Any, message: str) -> int:
    text = str(value if value is not None else "").strip()
    if not text:
        raise ValueError(message)
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(message) from exc


def _try_parse_float(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _try_parse_int(value: Any) -> int | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _try_resolve_surface_side(row: dict[str, Any]) -> str | None:
    surface_text = str(row.get("surface", "")).strip().lower()
    if surface_text:
        if surface_text in TOP_SURFACE_NAMES:
            return "top"
        if surface_text in BOTTOM_SURFACE_NAMES:
            return "bottom"
        return None

    y_value = _try_parse_float(row.get("y"))
    if y_value is None:
        return None
    if y_value > 0:
        return "top"
    if y_value < 0:
        return "bottom"
    return None


def _format_strain(value: Any) -> str:
    number = _try_parse_float(value)
    if number is not None:
        return f"{number:.6e}"
    text = str(value if value is not None else "").strip()
    return text or "未填写"
