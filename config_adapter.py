import copy
import json

import numpy as np


SAMPLE_CONFIG = {
    "node_x": [0.0, 1.0, 2.0, 3.0],
    "thickness": 0.0016,
    "material": {"elastic_modulus": 2.06e11},
    "gauss_n": 3,
    "points_per_element": 120,
    "elements_sensor_data": [
        {
            "measurements": [
                {
                    "x": 0.25,
                    "surface": "top",
                    "strain": 1.5503e-004,
                    "weight": 0.5,
                    "zone": [0.0, 0.5],
                },
                {
                    "x": 0.75,
                    "surface": "top",
                    "strain": 4.6495e-004,
                    "weight": 0.5,
                    "zone": [0.5, 1.0],
                },
                {
                    "x": 0.25,
                    "surface": "bot",
                    "strain": -1.5504e-004,
                    "weight": 0.5,
                    "zone": [0.0, 0.5],
                },
                {
                    "x": 0.75,
                    "surface": "bot",
                    "strain": -4.6496e-004,
                    "weight": 0.5,
                    "zone": [0.5, 1.0],
                },
            ]
        },
        {
            "measurements": [
                {
                    "x": 0.25,
                    "surface": "top",
                    "strain": 3.1769e-004,
                    "weight": 0.5,
                    "zone": [0.0, 0.5],
                },
                {
                    "x": 0.75,
                    "surface": "top",
                    "strain": 4.1466e-005,
                    "weight": 0.5,
                    "zone": [0.5, 1.0],
                },
                {
                    "x": 0.25,
                    "surface": "bot",
                    "strain": -3.1770e-004,
                    "weight": 0.5,
                    "zone": [0.0, 0.5],
                },
                {
                    "x": 0.75,
                    "surface": "bot",
                    "strain": -4.1469e-005,
                    "weight": 0.5,
                    "zone": [0.5, 1.0],
                },
            ]
        },
        {
            "measurements": [
                {
                    "x": 0.25,
                    "surface": "top",
                    "strain": -2.5058e-005,
                    "weight": 0.5,
                    "zone": [0.0, 0.5],
                },
                {
                    "x": 0.75,
                    "surface": "top",
                    "strain": -8.3578e-006,
                    "weight": 0.5,
                    "zone": [0.5, 1.0],
                },
                {
                    "x": 0.25,
                    "surface": "bot",
                    "strain": 2.5057e-005,
                    "weight": 0.5,
                    "zone": [0.0, 0.5],
                },
                {
                    "x": 0.75,
                    "surface": "bot",
                    "strain": 8.3578e-006,
                    "weight": 0.5,
                    "zone": [0.5, 1.0],
                },
            ]
        },
    ],
    "prescribed_dofs": {0: 0.0, 1: 0.0, 10: 0.0},
    "query_xs": [],
    "true_points": [
        {"x": 1.0, "u": -3.7376e-5, "v": 0.29134, "label": "实测点1"},
        {"x": 2.0, "u": 1.4562e-4, "v": 0.16811, "label": "实测点2"},
    ],
    "plot_options": {
        "show_original": True,
        "show_nodes": True,
        "equal_axis": False,
        "annotate_points": False,
        "connect_pairs": True,
        "title": "二维梁重构形态",
        "legend_loc": "best",
        "label_offset_scale": 0.04,
        "figsize": [11.0, 4.5],
        "thickness_scale": "auto",
        "field_representation": "nodal_average",
    },
}


DOF_TO_OFFSET = {"u": 0, "v": 1, "phi": 2}
OFFSET_TO_DOF = {value: key for key, value in DOF_TO_OFFSET.items()}


def get_sample_config():
    return copy.deepcopy(SAMPLE_CONFIG)


def parse_float_list(text, field_name):
    if text is None:
        return []
    stripped = str(text).strip()
    if not stripped:
        return []
    values = []
    for part in stripped.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError as exc:
            raise ValueError(f"{field_name} 中包含无法解析的数值：{token}") from exc
    return values


def _parse_form_float(value, field_name):
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空。")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是有效数值。") from exc


def _parse_form_int(value, field_name):
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空。")
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是有效整数。") from exc


def serialize_config(config):
    safe = copy.deepcopy(config)
    if "prescribed_dofs" in safe:
        safe["prescribed_dofs"] = {str(k): v for k, v in safe["prescribed_dofs"].items()}
    return safe


def config_to_json(config):
    return json.dumps(serialize_config(config), ensure_ascii=False, indent=2)


def load_config_from_json(text):
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc.msg}（第 {exc.lineno} 行，第 {exc.colno} 列）") from exc
    return normalize_config(raw)


def normalize_config(config):
    if not isinstance(config, dict):
        raise ValueError("配置必须是 JSON 对象。")

    normalized = copy.deepcopy(config)
    normalized.setdefault("gauss_n", 3)
    normalized.setdefault("points_per_element", 120)
    normalized.setdefault("query_xs", [])
    normalized.setdefault("true_points", [])
    normalized.setdefault("material", {})
    normalized.setdefault("plot_options", {})
    normalized["plot_options"].setdefault("show_original", True)
    normalized["plot_options"].setdefault("show_nodes", True)
    normalized["plot_options"].setdefault("equal_axis", False)
    normalized["plot_options"].setdefault("annotate_points", False)
    normalized["plot_options"].setdefault("connect_pairs", True)
    normalized["plot_options"].setdefault(
        "title", "二维梁重构形态"
    )
    normalized["plot_options"].setdefault("legend_loc", "best")
    normalized["plot_options"].setdefault("label_offset_scale", 0.04)
    normalized["plot_options"].setdefault("figsize", [11.0, 4.5])
    normalized["plot_options"].setdefault("y_limits", None)
    normalized["plot_options"].setdefault("thickness_scale", "auto")
    normalized["plot_options"].setdefault("field_representation", "nodal_average")

    field_representation = normalized["plot_options"].get("field_representation")
    if field_representation not in {"raw", "nodal_average"}:
        raise ValueError("plot_options.field_representation 必须是 raw 或 nodal_average。")

    thickness_scale = normalized["plot_options"].get("thickness_scale", "auto")
    if thickness_scale in (None, "", "auto"):
        normalized["plot_options"]["thickness_scale"] = "auto"
    else:
        thickness_scale = float(thickness_scale)
        if thickness_scale <= 0.0:
            raise ValueError("plot_options.thickness_scale 必须大于 0 或为 auto。")
        normalized["plot_options"]["thickness_scale"] = thickness_scale

    y_limits = normalized["plot_options"].get("y_limits")
    if y_limits not in (None, ""):
        if not isinstance(y_limits, list) or len(y_limits) != 2:
            raise ValueError("plot_options.y_limits 必须是 [y_min, y_max] 或 null。")
        y_min = float(y_limits[0])
        y_max = float(y_limits[1])
        if y_max <= y_min:
            raise ValueError("plot_options.y_limits 要求 y_max > y_min。")
        normalized["plot_options"]["y_limits"] = [y_min, y_max]
    else:
        normalized["plot_options"]["y_limits"] = None

    material = normalized.get("material") or {}
    if not isinstance(material, dict):
        raise ValueError("material 必须是对象。")
    elastic_modulus = material.get("elastic_modulus")
    if elastic_modulus in (None, ""):
        elastic_modulus = None
    else:
        elastic_modulus = float(elastic_modulus)
        if elastic_modulus <= 0.0:
            raise ValueError("material.elastic_modulus 必须大于 0。")
    normalized["material"] = {"elastic_modulus": elastic_modulus}

    prescribed = normalized.get("prescribed_dofs", {})
    if prescribed is None:
        prescribed = {}
    if not isinstance(prescribed, dict):
        raise ValueError("prescribed_dofs 必须是对象。")
    normalized["prescribed_dofs"] = {int(k): float(v) for k, v in prescribed.items()}

    elements_sensor_data = normalized.get("elements_sensor_data")
    if not isinstance(elements_sensor_data, list):
        raise ValueError("elements_sensor_data 必须是列表。")
    normalized["elements_sensor_data"] = elements_sensor_data

    true_points = normalized.get("true_points", [])
    if true_points is None:
        true_points = []
    if not isinstance(true_points, list):
        raise ValueError("true_points 必须是列表。")
    normalized["true_points"] = true_points

    query_xs = normalized.get("query_xs", [])
    if query_xs is None:
        query_xs = []
    if isinstance(query_xs, str):
        query_xs = parse_float_list(query_xs, "query_xs")
    if not isinstance(query_xs, list):
        raise ValueError("query_xs 必须是列表。")
    normalized["query_xs"] = [float(x) for x in query_xs]

    node_x = normalized.get("node_x")
    if node_x is None:
        raise ValueError("缺少 node_x。")
    if isinstance(node_x, str):
        node_x = parse_float_list(node_x, "node_x")
    if not isinstance(node_x, list):
        raise ValueError("node_x 必须是列表。")
    normalized["node_x"] = [float(x) for x in node_x]

    if "thickness" not in normalized:
        raise ValueError("缺少 thickness。")
    normalized["thickness"] = float(normalized["thickness"])
    normalized["gauss_n"] = int(normalized["gauss_n"])
    normalized["points_per_element"] = int(normalized["points_per_element"])

    return normalized


def make_global_dof(node_index, dof_name):
    dof_name = str(dof_name).strip().lower()
    if dof_name not in DOF_TO_OFFSET:
        raise ValueError("自由度类型必须是 u、v 或 phi。")
    return int(node_index) * 3 + DOF_TO_OFFSET[dof_name]


def global_dof_to_pair(global_dof):
    global_dof = int(global_dof)
    node = global_dof // 3
    dof = OFFSET_TO_DOF[global_dof % 3]
    return node, dof


def validate_config(config, *, require_measurements=True):
    config = normalize_config(config)

    node_x = config["node_x"]
    if len(node_x) < 2:
        raise ValueError("节点数至少应为 2。")
    if any(node_x[i + 1] <= node_x[i] for i in range(len(node_x) - 1)):
        raise ValueError("node_x 必须严格递增。")

    if config["thickness"] <= 0:
        raise ValueError("thickness 必须大于 0。")

    if config["gauss_n"] not in (2, 3, 4):
        raise ValueError("gauss_n 仅支持 2、3、4。")

    if config["points_per_element"] < 2:
        raise ValueError("points_per_element 至少应为 2。")

    n_elems = len(node_x) - 1
    elements_sensor_data = config["elements_sensor_data"]
    if len(elements_sensor_data) != n_elems:
        raise ValueError(
            "elements_sensor_data 的长度必须等于单元数 len(node_x)-1。"
        )

    for e, edata in enumerate(elements_sensor_data):
        measurements = edata.get("measurements", [])
        if require_measurements and not measurements:
            raise ValueError(f"第 {e} 个单元至少需要一条 measurement。")
        Le = node_x[e + 1] - node_x[e]
        for idx, measurement in enumerate(measurements):
            if "x" not in measurement or "strain" not in measurement:
                raise ValueError(f"第 {e} 个单元第 {idx} 条 measurement 缺少 x 或 strain。")
            x_loc = float(measurement["x"])
            if x_loc < 0.0 or x_loc > Le:
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 的 x 超出局部范围 [0, {Le}]。"
                )
            zone = measurement.get("zone")
            if not isinstance(zone, list) or len(zone) != 2:
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 的 zone 必须是长度为 2 的列表。"
                )
            a = float(zone[0])
            b = float(zone[1])
            if a < 0.0 or b > Le or b <= a:
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 的 zone 不合法。"
                )
            has_surface = measurement.get("surface") not in (None, "")
            has_y = measurement.get("y") not in (None, "")
            if not (has_surface or has_y):
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 需要填写 surface 或 y。"
                )

    max_node_index = len(node_x) - 1
    seen_dofs = set()
    for dof, value in config["prescribed_dofs"].items():
        dof = int(dof)
        node_idx, _ = global_dof_to_pair(dof)
        if node_idx < 0 or node_idx > max_node_index:
            raise ValueError(f"边界条件自由度 {dof} 对应的节点超出范围。")
        if dof in seen_dofs:
            raise ValueError(f"存在重复的边界条件自由度：{dof}")
        seen_dofs.add(dof)
        float(value)

    beam_start = node_x[0]
    beam_end = node_x[-1]
    for xq in config["query_xs"]:
        if xq < beam_start or xq > beam_end:
            raise ValueError(
                f"查询点 x={xq} 超出梁长范围 [{beam_start}, {beam_end}]。"
            )

    for idx, point in enumerate(config["true_points"], start=1):
        if "x" not in point:
            raise ValueError(f"第 {idx} 个实测对比点缺少 x。")
        x0 = float(point["x"])
        if x0 < beam_start or x0 > beam_end:
            raise ValueError(
                f"第 {idx} 个实测对比点 x={x0} 超出梁长范围 [{beam_start}, {beam_end}]。"
            )
        float(point.get("u", 0.0))
        float(point.get("v", 0.0))

    return config


def build_config_from_form_data(
    *,
    node_x_text,
    thickness_text,
    gauss_n_text,
    points_per_element_text,
    query_xs_text,
    measurement_rows,
    boundary_rows,
    true_point_rows,
    plot_options,
    elastic_modulus_gpa_text="",
    require_measurements=True,
):
    node_x = parse_float_list(node_x_text, "node_x")
    thickness = _parse_form_float(thickness_text, "梁厚度 thickness")
    gauss_n = _parse_form_int(gauss_n_text, "高斯点数 gauss_n")
    points_per_element = _parse_form_int(
        points_per_element_text, "曲线采样数 points_per_element"
    )
    query_xs = parse_float_list(query_xs_text, "query_xs")
    elastic_modulus_value = str(elastic_modulus_gpa_text).strip()
    elastic_modulus = (
        _parse_form_float(elastic_modulus_value, "弹性模量") * 1.0e9
        if elastic_modulus_value
        else None
    )

    if len(node_x) < 2:
        raise ValueError("node_x 至少需要两个节点坐标。")

    n_elems = len(node_x) - 1
    elements_sensor_data = [{"measurements": []} for _ in range(n_elems)]

    for idx, row in enumerate(measurement_rows, start=1):
        element_text = str(row.get("element", "")).strip()
        if not element_text:
            raise ValueError(f"第 {idx} 条测量数据缺少单元号。")
        element = _parse_form_int(element_text, f"第 {idx} 条测量数据的单元号")
        if element < 0 or element >= n_elems:
            raise ValueError(f"第 {idx} 条测量数据的单元号超出范围。")

        x_loc = _parse_form_float(row.get("x", ""), f"第 {idx} 条测量数据的 x")
        strain = _parse_form_float(
            row.get("strain", ""), f"第 {idx} 条测量数据的应变"
        )
        weight_text = str(row.get("weight", "")).strip()
        weight = (
            _parse_form_float(weight_text, f"第 {idx} 条测量数据的权重")
            if weight_text
            else 1.0
        )
        zone_a = _parse_form_float(
            row.get("zone_a", ""), f"第 {idx} 条测量数据的量长起点"
        )
        zone_b = _parse_form_float(
            row.get("zone_b", ""), f"第 {idx} 条测量数据的量长终点"
        )

        measurement = {
            "x": x_loc,
            "strain": strain,
            "weight": weight,
            "zone": [zone_a, zone_b],
        }

        surface_text = str(row.get("surface", "")).strip()
        y_text = str(row.get("y", "")).strip()
        if surface_text:
            measurement["surface"] = surface_text
        elif y_text:
            measurement["y"] = _parse_form_float(
                y_text, f"第 {idx} 条测量数据的截面 y"
            )
        else:
            raise ValueError(f"第 {idx} 条测量数据需要填写 surface 或 y。")

        elements_sensor_data[element]["measurements"].append(measurement)

    prescribed_dofs = {}
    for idx, row in enumerate(boundary_rows, start=1):
        node_text = str(row.get("node", "")).strip()
        dof_text = str(row.get("dof", "")).strip().lower()
        value_text = str(row.get("value", "")).strip()
        if not node_text or not dof_text or not value_text:
            raise ValueError(f"第 {idx} 条边界条件未填写完整。")
        try:
            global_dof = make_global_dof(
                _parse_form_int(node_text, f"第 {idx} 条边界条件的节点号"),
                dof_text,
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(f"第 {idx} 条边界条件的节点号或自由度不合法。") from exc
        if global_dof in prescribed_dofs:
            raise ValueError(f"存在重复边界条件：节点 {node_text} 的 {dof_text}。")
        prescribed_dofs[global_dof] = _parse_form_float(
            value_text, f"第 {idx} 条边界条件的约束值"
        )

    true_points = []
    for idx, row in enumerate(true_point_rows, start=1):
        x_text = str(row.get("x", "")).strip()
        if not x_text:
            raise ValueError(f"第 {idx} 条实测点缺少 x。")
        point = {"x": _parse_form_float(x_text, f"第 {idx} 条实测对比点的 x")}
        label = str(row.get("label", "")).strip()
        if label:
            point["label"] = label
        u_text = str(row.get("u", "")).strip()
        v_text = str(row.get("v", "")).strip()
        point["u"] = (
            _parse_form_float(u_text, f"第 {idx} 条实测对比点的 u")
            if u_text
            else 0.0
        )
        point["v"] = (
            _parse_form_float(v_text, f"第 {idx} 条实测对比点的 v")
            if v_text
            else 0.0
        )
        true_points.append(point)

    config = {
        "node_x": node_x,
        "thickness": thickness,
        "material": {"elastic_modulus": elastic_modulus},
        "gauss_n": gauss_n,
        "points_per_element": points_per_element,
        "elements_sensor_data": elements_sensor_data,
        "prescribed_dofs": prescribed_dofs,
        "query_xs": query_xs,
        "true_points": true_points,
        "plot_options": plot_options,
    }
    return validate_config(config, require_measurements=require_measurements)


def boundary_rows_from_prescribed_dofs(prescribed_dofs):
    rows = []
    for global_dof in sorted(prescribed_dofs):
        node, dof = global_dof_to_pair(global_dof)
        rows.append(
            {"node": str(node), "dof": dof, "value": f"{float(prescribed_dofs[global_dof]):.12g}"}
        )
    return rows


def measurement_rows_from_config(config):
    rows = []
    for element, edata in enumerate(config["elements_sensor_data"]):
        for measurement in edata.get("measurements", []):
            rows.append(
                {
                    "element": str(element),
                    "x": f"{float(measurement['x']):.12g}",
                    "surface": str(measurement.get("surface", "")),
                    "y": "" if "y" not in measurement else f"{float(measurement['y']):.12g}",
                    "strain": f"{float(measurement['strain']):.12g}",
                    "weight": f"{float(measurement.get('weight', 1.0)):.12g}",
                    "zone_a": f"{float(measurement['zone'][0]):.12g}",
                    "zone_b": f"{float(measurement['zone'][1]):.12g}",
                }
            )
    return rows


def true_point_rows_from_config(config):
    rows = []
    for point in config.get("true_points", []):
        rows.append(
            {
                "label": str(point.get("label", "")),
                "x": f"{float(point['x']):.12g}",
                "u": f"{float(point.get('u', 0.0)):.12g}",
                "v": f"{float(point.get('v', 0.0)):.12g}",
            }
        )
    return rows


def build_model_inputs(config):
    config = validate_config(config)
    return {
        "node_x": np.asarray(config["node_x"], dtype=float),
        "thickness": float(config["thickness"]),
        "elements_sensor_data": config["elements_sensor_data"],
        "prescribed_dofs": {int(k): float(v) for k, v in config["prescribed_dofs"].items()},
        "gauss_n": int(config["gauss_n"]),
        "points_per_element": int(config["points_per_element"]),
        "query_xs": [float(x) for x in config["query_xs"]],
        "true_points": config["true_points"] or None,
        "material": config["material"],
        "plot_options": config["plot_options"],
    }


def run_reconstruction(config):
    from ifem.application.analysis_service import get_default_analysis_service

    result = get_default_analysis_service().run(config)
    return result.native_model, dict(result.inputs)
