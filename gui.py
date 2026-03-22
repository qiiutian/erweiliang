import tkinter as tk
from tkinter import messagebox, ttk

import matplotlib
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config_adapter import (
    build_config_from_form_data,
    boundary_rows_from_prescribed_dofs,
    config_to_json,
    get_sample_config,
    load_config_from_json,
    measurement_rows_from_config,
    run_reconstruction,
    true_point_rows_from_config,
)


matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "SimSun", "Arial Unicode MS"]
matplotlib.rcParams["axes.unicode_minus"] = False


class TableEditor(ttk.Frame):
    def __init__(self, master, title, field_specs, height=8):
        super().__init__(master)
        self.field_specs = field_specs
        self.vars = {}

        frame = ttk.LabelFrame(self, text=title)
        frame.pack(fill="both", expand=True)

        columns = [spec["key"] for spec in field_specs]
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
        for spec in field_specs:
            self.tree.heading(spec["key"], text=spec["label"])
            self.tree.column(spec["key"], width=spec.get("width", 100), anchor="center")

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)

        form = ttk.Frame(frame)
        form.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        for idx, spec in enumerate(field_specs):
            row = idx // 4
            col = (idx % 4) * 2
            ttk.Label(form, text=spec["label"]).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=4)
            variable = tk.StringVar()
            self.vars[spec["key"]] = variable
            if spec.get("choices"):
                widget = ttk.Combobox(
                    form,
                    textvariable=variable,
                    values=spec["choices"],
                    width=spec.get("entry_width", 12),
                    state="readonly",
                )
            else:
                widget = ttk.Entry(form, textvariable=variable, width=spec.get("entry_width", 14))
            widget.grid(row=row, column=col + 1, sticky="ew", padx=(0, 12), pady=4)

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(button_bar, text="新增", command=self.add_row).pack(side="left", padx=(0, 6))
        ttk.Button(button_bar, text="更新选中", command=self.update_selected).pack(side="left", padx=(0, 6))
        ttk.Button(button_bar, text="删除选中", command=self.delete_selected).pack(side="left", padx=(0, 6))
        ttk.Button(button_bar, text="清空表格", command=self.clear_rows).pack(side="left")

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

    def get_form_values(self):
        return {spec["key"]: self.vars[spec["key"]].get().strip() for spec in self.field_specs}

    def set_form_values(self, values):
        for spec in self.field_specs:
            self.vars[spec["key"]].set(values.get(spec["key"], ""))

    def clear_form(self):
        for var in self.vars.values():
            var.set("")

    def add_row(self):
        values = self.get_form_values()
        self.tree.insert("", "end", values=[values[spec["key"]] for spec in self.field_specs])
        self.clear_form()

    def update_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        values = self.get_form_values()
        for item_id in selected:
            self.tree.item(item_id, values=[values[spec["key"]] for spec in self.field_specs])

    def delete_selected(self):
        for item_id in self.tree.selection():
            self.tree.delete(item_id)

    def clear_rows(self):
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.clear_form()

    def on_select(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        payload = {spec["key"]: values[idx] for idx, spec in enumerate(self.field_specs)}
        self.set_form_values(payload)

    def get_rows(self):
        rows = []
        for item_id in self.tree.get_children():
            values = self.tree.item(item_id, "values")
            rows.append({spec["key"]: values[idx] for idx, spec in enumerate(self.field_specs)})
        return rows

    def set_rows(self, rows):
        self.clear_rows()
        for row in rows:
            self.tree.insert("", "end", values=[row.get(spec["key"], "") for spec in self.field_specs])


class ResultTable(ttk.Frame):
    def __init__(self, master, columns, headings, height=8):
        super().__init__(master)
        self.columns = columns
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=height)
        for column, heading in zip(columns, headings):
            self.tree.heading(column, text=heading)
            self.tree.column(column, anchor="center", width=110)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def clear(self):
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

    def set_rows(self, rows):
        self.clear()
        for row in rows:
            values = [row.get(column, "") for column in self.columns]
            self.tree.insert("", "end", values=values)


class ReconstructionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("二维梁形状重构桌面工具")
        self.root.geometry("1680x980")
        self.root.minsize(1320, 820)

        self.current_model = None
        self.current_config = None
        self._resize_after_id = None
        self._split_after_id = None

        self._build_variables()
        self._build_layout()
        self.load_sample_data()

    def _build_variables(self):
        self.node_x_var = tk.StringVar()
        self.thickness_var = tk.StringVar()
        self.gauss_n_var = tk.StringVar(value="3")
        self.points_per_element_var = tk.StringVar(value="120")
        self.query_xs_var = tk.StringVar()
        self.title_var = tk.StringVar(value="直接表面应变矩阵法二维梁形状重构结果")
        self.y_min_var = tk.StringVar()
        self.y_max_var = tk.StringVar()
        self.show_original_var = tk.BooleanVar(value=True)
        self.show_nodes_var = tk.BooleanVar(value=True)
        self.equal_axis_var = tk.BooleanVar(value=False)
        self.annotate_points_var = tk.BooleanVar(value=True)
        self.connect_pairs_var = tk.BooleanVar(value=True)
        self.legend_summary = ""

    def _build_layout(self):
        container = ttk.PanedWindow(self.root, orient="horizontal")
        container.pack(fill="both", expand=True)

        left = ttk.Frame(container, padding=8)
        right = ttk.Frame(container, padding=8)
        container.add(left, weight=3)
        container.add(right, weight=4)

        self._build_left_panel(left)
        self._build_right_panel(right)

    def _build_left_panel(self, parent):
        command_bar = ttk.Frame(parent)
        command_bar.pack(fill="x", pady=(0, 8))
        ttk.Button(command_bar, text="运行重构", command=self.run_reconstruction).pack(side="left", padx=(0, 6))
        ttk.Button(command_bar, text="加载示例数据", command=self.load_sample_data).pack(side="left", padx=(0, 6))
        ttk.Button(command_bar, text="表单生成 JSON", command=self.refresh_json_from_form).pack(side="left", padx=(0, 6))
        ttk.Button(command_bar, text="JSON 导入表单", command=self.import_json_to_form).pack(side="left")

        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True)

        basic_tab = ttk.Frame(notebook, padding=8)
        measure_tab = ttk.Frame(notebook, padding=8)
        boundary_tab = ttk.Frame(notebook, padding=8)
        optional_tab = ttk.Frame(notebook, padding=8)
        json_tab = ttk.Frame(notebook, padding=8)

        notebook.add(basic_tab, text="基本参数")
        notebook.add(measure_tab, text="测量数据")
        notebook.add(boundary_tab, text="边界条件")
        notebook.add(optional_tab, text="可选数据")
        notebook.add(json_tab, text="JSON")

        self._build_basic_tab(basic_tab)
        self._build_measure_tab(measure_tab)
        self._build_boundary_tab(boundary_tab)
        self._build_optional_tab(optional_tab)
        self._build_json_tab(json_tab)

    def _build_right_panel(self, parent):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        self.right_panel_container = container
        self.right_split = ttk.PanedWindow(container, orient="vertical")
        self.right_split.grid(row=0, column=0, sticky="nsew")

        self.plot_frame = ttk.LabelFrame(self.right_split, text="重构图")
        result_frame = ttk.Frame(self.right_split)
        self.result_frame = result_frame
        self.right_split.add(self.plot_frame, weight=3)
        self.right_split.add(result_frame, weight=2)
        self.right_panel_container.bind("<Configure>", self._schedule_split_constraints)
        self.right_split.bind("<ButtonRelease-1>", self._schedule_split_constraints)
        self.right_split.bind("<B1-Motion>", self._schedule_split_constraints)
        self.root.after(120, self._schedule_split_constraints)

        self.figure = Figure(figsize=(8.8, 4.8), dpi=100)
        self.axes = self.figure.add_subplot(111)
        self.canvas_frame = ttk.Frame(self.plot_frame)
        self.canvas_frame.pack(fill="both", expand=True)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.canvas_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.plot_frame.bind("<Configure>", self._on_plot_frame_resize)

        result_notebook = ttk.Notebook(result_frame)
        result_notebook.pack(fill="both", expand=True)

        node_tab = ttk.Frame(result_notebook, padding=6)
        query_tab = ttk.Frame(result_notebook, padding=6)
        compare_tab = ttk.Frame(result_notebook, padding=6)
        message_tab = ttk.Frame(result_notebook, padding=6)
        result_notebook.add(node_tab, text="节点结果")
        result_notebook.add(query_tab, text="查询结果")
        result_notebook.add(compare_tab, text="实测对比")
        result_notebook.add(message_tab, text="运行信息")

        self.node_result_table = ResultTable(
            node_tab,
            columns=["节点", "x坐标", "u位移", "v位移", "转角phi"],
            headings=["节点", "x坐标", "u位移", "v位移", "转角phi"],
            height=12,
        )
        self.node_result_table.pack(fill="both", expand=True)

        self.query_result_table = ResultTable(
            query_tab,
            columns=["序号", "x", "u", "v"],
            headings=["序号", "x坐标", "u位移", "v位移"],
            height=12,
        )
        self.query_result_table.pack(fill="both", expand=True)

        self.compare_result_table = ResultTable(
            compare_tab,
            columns=["序号", "标签", "x", "u_实测", "v_实测", "u_重构", "v_重构", "Δu", "Δv"],
            headings=["序号", "标签", "x坐标", "u实测", "v实测", "u重构", "v重构", "Δu", "Δv"],
            height=12,
        )
        self.compare_result_table.pack(fill="both", expand=True)

        self.message_text = tk.Text(message_tab, wrap="word", height=12)
        self.message_text.pack(fill="both", expand=True)

    def _on_plot_frame_resize(self, _event=None):
        if self._resize_after_id is not None:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(80, self._resize_figure_to_container)

    def _schedule_split_constraints(self, _event=None):
        if self._split_after_id is not None:
            self.root.after_cancel(self._split_after_id)
        self._split_after_id = self.root.after(30, self._enforce_split_constraints)

    def _enforce_split_constraints(self):
        self._split_after_id = None
        total_height = self.right_split.winfo_height()
        if total_height <= 0:
            return

        sash_index = 0
        try:
            current_pos = int(self.right_split.sashpos(sash_index))
        except tk.TclError:
            return

        min_plot_height = 280
        min_result_height = 220
        max_plot_height = max(min_plot_height, total_height - min_result_height)
        clamped_pos = min(max(current_pos, min_plot_height), max_plot_height)

        if clamped_pos != current_pos:
            self.right_split.sashpos(sash_index, clamped_pos)
            self._on_plot_frame_resize()

    def _resize_figure_to_container(self):
        self._resize_after_id = None
        width = self.canvas_frame.winfo_width()
        height = self.canvas_frame.winfo_height()
        if width <= 40 or height <= 60:
            return

        usable_width = max(width - 24, 320)
        usable_height = max(height - 24, 220)
        dpi = self.figure.get_dpi()
        self.figure.set_size_inches(usable_width / dpi, usable_height / dpi, forward=True)
        self.figure.tight_layout(pad=1.2)
        self.canvas.draw_idle()

    def _build_basic_tab(self, parent):
        form = ttk.LabelFrame(parent, text="基本参数")
        form.pack(fill="x")
        form.columnconfigure(1, weight=3)
        form.columnconfigure(3, weight=2)
        form.columnconfigure(5, weight=2)

        ttk.Label(form, text="节点 x 坐标").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(form, textvariable=self.node_x_var).grid(
            row=0, column=1, columnspan=5, sticky="ew", padx=6, pady=6
        )

        ttk.Label(form, text="梁厚度 thickness").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(form, textvariable=self.thickness_var, width=18).grid(
            row=1, column=1, sticky="ew", padx=6, pady=6
        )
        ttk.Label(form, text="高斯点数 gauss_n").grid(row=1, column=2, sticky="w", padx=6, pady=6)
        ttk.Entry(form, textvariable=self.gauss_n_var, width=10).grid(
            row=1, column=3, sticky="ew", padx=6, pady=6
        )
        ttk.Label(form, text="每单元采样点数").grid(row=1, column=4, sticky="w", padx=6, pady=6)
        ttk.Entry(form, textvariable=self.points_per_element_var, width=12).grid(
            row=1, column=5, sticky="ew", padx=6, pady=6
        )

        ttk.Label(form, text="图标题").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(form, textvariable=self.title_var).grid(
            row=2, column=1, columnspan=5, sticky="ew", padx=6, pady=6
        )

        ttk.Label(form, text="查询点 x 列表").grid(row=3, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(form, textvariable=self.query_xs_var).grid(
            row=3, column=1, columnspan=5, sticky="ew", padx=6, pady=6
        )

        ttk.Label(form, text="Y轴最小值").grid(row=4, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(form, textvariable=self.y_min_var, width=16).grid(
            row=4, column=1, sticky="ew", padx=6, pady=6
        )
        ttk.Label(form, text="Y轴最大值").grid(row=4, column=2, sticky="w", padx=6, pady=6)
        ttk.Entry(form, textvariable=self.y_max_var, width=16).grid(
            row=4, column=3, sticky="ew", padx=6, pady=6
        )

        ttk.Label(form, text="Y轴最小值和最大值同时留空时为自动缩放。").grid(
            row=5, column=0, columnspan=6, sticky="w", padx=6, pady=(0, 4)
        )

        options = ttk.LabelFrame(parent, text="显示选项")
        options.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(options, text="显示原始中性层", variable=self.show_original_var).grid(
            row=0, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Checkbutton(options, text="显示重构节点", variable=self.show_nodes_var).grid(
            row=0, column=1, sticky="w", padx=8, pady=6
        )
        ttk.Checkbutton(options, text="等比例坐标轴", variable=self.equal_axis_var).grid(
            row=0, column=2, sticky="w", padx=8, pady=6
        )
        ttk.Checkbutton(options, text="标注实测/重构点", variable=self.annotate_points_var).grid(
            row=1, column=0, sticky="w", padx=8, pady=6
        )
        ttk.Checkbutton(options, text="连线显示差异", variable=self.connect_pairs_var).grid(
            row=1, column=1, sticky="w", padx=8, pady=6
        )

    def _build_measure_tab(self, parent):
        specs = [
            {"key": "element", "label": "单元号", "width": 70},
            {"key": "x", "label": "x", "width": 80},
            {"key": "surface", "label": "surface", "width": 90, "choices": ["", "top", "bot", "上", "下"]},
            {"key": "y", "label": "y", "width": 80},
            {"key": "strain", "label": "strain", "width": 110},
            {"key": "weight", "label": "weight", "width": 80},
            {"key": "zone_a", "label": "zone起点", "width": 90},
            {"key": "zone_b", "label": "zone终点", "width": 90},
        ]
        self.measurement_editor = TableEditor(parent, "测量数据", specs, height=14)
        self.measurement_editor.pack(fill="both", expand=True)

    def _build_boundary_tab(self, parent):
        specs = [
            {"key": "node", "label": "节点号", "width": 80},
            {"key": "dof", "label": "自由度", "width": 80, "choices": ["u", "v", "phi"]},
            {"key": "value", "label": "约束值", "width": 100},
        ]
        self.boundary_editor = TableEditor(parent, "边界条件", specs, height=10)
        self.boundary_editor.pack(fill="both", expand=True)

        tip = ttk.Label(
            parent,
            text="界面使用 节点号 + 自由度(u/v/phi) 录入，程序会自动转换为全局自由度编号。",
        )
        tip.pack(anchor="w", pady=(8, 0))

    def _build_optional_tab(self, parent):
        specs = [
            {"key": "label", "label": "标签", "width": 100},
            {"key": "x", "label": "x", "width": 90},
            {"key": "u", "label": "u实测", "width": 100},
            {"key": "v", "label": "v实测", "width": 100},
        ]
        self.true_point_editor = TableEditor(parent, "实测对比点", specs, height=10)
        self.true_point_editor.pack(fill="both", expand=True)

    def _build_json_tab(self, parent):
        self.json_text = tk.Text(parent, wrap="none")
        self.json_text.pack(fill="both", expand=True)

    def _collect_plot_options(self):
        y_min_text = self.y_min_var.get().strip()
        y_max_text = self.y_max_var.get().strip()
        if y_min_text or y_max_text:
            if not (y_min_text and y_max_text):
                raise ValueError("手动设置 Y 轴时，Y轴最小值和最大值必须同时填写。")
            y_limits = [float(y_min_text), float(y_max_text)]
            if y_limits[1] <= y_limits[0]:
                raise ValueError("Y 轴范围不合法，要求最大值大于最小值。")
        else:
            y_limits = None

        return {
            "show_original": bool(self.show_original_var.get()),
            "show_nodes": bool(self.show_nodes_var.get()),
            "equal_axis": bool(self.equal_axis_var.get()),
            "annotate_points": bool(self.annotate_points_var.get()),
            "connect_pairs": bool(self.connect_pairs_var.get()),
            "title": self.title_var.get().strip() or "直接表面应变矩阵法二维梁形状重构结果",
            "legend_loc": "best",
            "label_offset_scale": 0.04,
            "figsize": [11.0, 4.5],
            "y_limits": y_limits,
        }

    def _build_form_config(self):
        return build_config_from_form_data(
            node_x_text=self.node_x_var.get(),
            thickness_text=self.thickness_var.get(),
            gauss_n_text=self.gauss_n_var.get(),
            points_per_element_text=self.points_per_element_var.get(),
            query_xs_text=self.query_xs_var.get(),
            measurement_rows=self.measurement_editor.get_rows(),
            boundary_rows=self.boundary_editor.get_rows(),
            true_point_rows=self.true_point_editor.get_rows(),
            plot_options=self._collect_plot_options(),
        )

    def refresh_json_from_form(self):
        try:
            config = self._build_form_config()
        except Exception as exc:
            self._handle_error(exc)
            return
        self._set_json_text(config_to_json(config))
        self._write_message("已根据当前表单生成 JSON 配置。")

    def import_json_to_form(self):
        try:
            config = load_config_from_json(self.json_text.get("1.0", "end").strip())
            self._load_config_to_form(config)
            self._write_message("JSON 已导入到表单。")
        except Exception as exc:
            self._handle_error(exc)

    def load_sample_data(self):
        config = get_sample_config()
        self._load_config_to_form(config)
        self._set_json_text(config_to_json(config))
        self._write_message("已加载示例数据。")

    def _load_config_to_form(self, config):
        self.node_x_var.set(", ".join(f"{x:.12g}" for x in config["node_x"]))
        self.thickness_var.set(f"{float(config['thickness']):.12g}")
        self.gauss_n_var.set(str(config.get("gauss_n", 3)))
        self.points_per_element_var.set(str(config.get("points_per_element", 120)))
        self.query_xs_var.set(", ".join(f"{float(x):.12g}" for x in config.get("query_xs", [])))

        plot_options = config.get("plot_options", {})
        self.title_var.set(plot_options.get("title", "直接表面应变矩阵法二维梁形状重构结果"))
        y_limits = plot_options.get("y_limits")
        if isinstance(y_limits, (list, tuple)) and len(y_limits) == 2:
            self.y_min_var.set(f"{float(y_limits[0]):.12g}")
            self.y_max_var.set(f"{float(y_limits[1]):.12g}")
        else:
            self.y_min_var.set("")
            self.y_max_var.set("")
        self.show_original_var.set(bool(plot_options.get("show_original", True)))
        self.show_nodes_var.set(bool(plot_options.get("show_nodes", True)))
        self.equal_axis_var.set(bool(plot_options.get("equal_axis", False)))
        self.annotate_points_var.set(bool(plot_options.get("annotate_points", True)))
        self.connect_pairs_var.set(bool(plot_options.get("connect_pairs", True)))

        self.measurement_editor.set_rows(measurement_rows_from_config(config))
        self.boundary_editor.set_rows(boundary_rows_from_prescribed_dofs(config["prescribed_dofs"]))
        self.true_point_editor.set_rows(true_point_rows_from_config(config))

    def run_reconstruction(self):
        try:
            config = self._build_form_config()
            model, inputs = run_reconstruction(config)
            self.current_model = model
            self.current_config = config
            self._set_json_text(config_to_json(config))
            self._render_plot(model, inputs)
            self._fill_result_tables(model, inputs)
            self._write_message(
                "重构完成。\n"
                f"节点数: {model.n_nodes}\n"
                f"单元数: {model.n_elems}\n"
                f"高斯点数: {inputs['gauss_n']}\n"
                f"每单元采样点数: {inputs['points_per_element']}"
            )
        except Exception as exc:
            self._handle_error(exc)

    def _render_plot(self, model, inputs):
        plot_options = dict(inputs["plot_options"])
        plot_options.pop("figsize", None)
        title = plot_options.pop("title", "直接表面应变矩阵法二维梁形状重构结果")
        y_limits = plot_options.get("y_limits")

        model.plot_on_axes(
            self.axes,
            points_per_element=inputs["points_per_element"],
            true_points=inputs["true_points"],
            title=title,
            show_legend=False,
            **plot_options,
        )
        self._update_external_legend(plot_options, inputs["true_points"], y_limits)
        self._resize_figure_to_container()

    def _update_external_legend(self, plot_options, true_points, y_limits):
        legend_items = []
        if plot_options.get("show_original", True):
            legend_items.append("原始中性层: 黑色虚线")
        legend_items.append("重构后形状: 蓝色实线")
        if plot_options.get("show_nodes", True):
            legend_items.append("重构节点: 蓝色圆点")

        if true_points:
            legend_items.append("输入实测点: 红色圆点")
            legend_items.append("同位置重构点: 绿色方点")
            if plot_options.get("connect_pairs", True):
                legend_items.append("实测-重构差异: 灰色虚线")

        if y_limits is not None:
            legend_items.append(f"Y轴范围: {y_limits[0]:.6g} ~ {y_limits[1]:.6g}")
        else:
            legend_items.append("Y轴范围: 自动")

        self.legend_summary = "图例：\n" + "\n".join(f"- {item}" for item in legend_items)

    def _fill_result_tables(self, model, inputs):
        node_rows = []
        for row in model.nodal_results_table():
            node_rows.append(
                {
                    "节点": row["节点"],
                    "x坐标": f"{row['x坐标']:.6f}",
                    "u位移": f"{row['u位移']:.6e}",
                    "v位移": f"{row['v位移']:.6e}",
                    "转角phi": f"{row['转角phi']:.6e}",
                }
            )
        self.node_result_table.set_rows(node_rows)

        query_rows = []
        for idx, row in enumerate(model.evaluate_displacement_at_points(inputs["query_xs"]), start=1):
            query_rows.append(
                {
                    "序号": idx,
                    "x": f"{row['x']:.6f}",
                    "u": f"{row['u']:.6e}",
                    "v": f"{row['v']:.6e}",
                }
            )
        self.query_result_table.set_rows(query_rows)

        compare_rows = []
        for row in model.compare_true_points(inputs["true_points"]):
            compare_rows.append(
                {
                    "序号": row["序号"],
                    "标签": row["标签"],
                    "x": f"{row['x']:.6f}",
                    "u_实测": f"{row['u_实测']:.6e}",
                    "v_实测": f"{row['v_实测']:.6e}",
                    "u_重构": f"{row['u_重构']:.6e}",
                    "v_重构": f"{row['v_重构']:.6e}",
                    "Δu": f"{row['Δu']:.6e}",
                    "Δv": f"{row['Δv']:.6e}",
                }
            )
        self.compare_result_table.set_rows(compare_rows)

    def _set_json_text(self, content):
        self.json_text.delete("1.0", "end")
        self.json_text.insert("1.0", content)

    def _write_message(self, message):
        self.message_text.delete("1.0", "end")
        if self.legend_summary:
            self.message_text.insert("1.0", f"{message}\n\n{self.legend_summary}")
        else:
            self.message_text.insert("1.0", message)

    def _handle_error(self, exc):
        message = str(exc)
        self._write_message(f"运行失败：\n{message}")
        messagebox.showerror("错误", message)


def launch_app():
    root = tk.Tk()
    app = ReconstructionApp(root)
    root.mainloop()
    return app
