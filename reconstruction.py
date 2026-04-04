import numpy as np


class IBeam3SurfaceIntegralReconstruction2D:
    """
    二维梁直接表面应变矩阵法形状重构（积分型，方案 B，手动积分分区版）

    采用：
        ε(x, y) = ε0(x) - y κ(x)
        ε0(x) = Bb(x) u_e
        κ(x)  = Bm(x) u_e
        => ε(x, y) = (Bb(x) - y Bm(x)) u_e

    单元误差泛函采用积分型形式：
        Φ_e(u_e) = Σ_p ∫_{a_p}^{b_p} w_p [B_p(x)u_e - ε̄_p]^2 dx

    每条测量 p 由用户指定：
        - 测点位置 x
        - 表面 surface 或 y
        - 测量应变 strain
        - 权重 weight
        - 积分区域 zone = [a, b]
    """

    def __init__(self, node_x, thickness, elements_sensor_data):
        self.node_x = np.asarray(node_x, dtype=float)
        self.thickness = float(thickness)
        self.h = self.thickness / 2.0
        self.elements_sensor_data = elements_sensor_data

        self.n_nodes = len(self.node_x)
        self.n_elems = self.n_nodes - 1
        self.ndof = self.n_nodes * 3

        if self.n_nodes < 2:
            raise ValueError("节点数至少应为 2。")

        if np.any(np.diff(self.node_x) <= 0):
            raise ValueError("node_x 必须严格递增。")

        if len(elements_sensor_data) != self.n_elems:
            raise ValueError(
                "elements_sensor_data 的长度必须等于单元数 n_elements = len(node_x)-1"
            )

        self.K = np.zeros((self.ndof, self.ndof), dtype=float)
        self.F = np.zeros(self.ndof, dtype=float)
        self.U = None

    @staticmethod
    def shape_functions(x, Le):
        N1 = 1.0 - x / Le
        N2 = (Le**3 - 3.0 * Le * x**2 + 2.0 * x**3) / Le**3
        N3 = (Le**3 * x - 2.0 * Le**2 * x**2 + Le * x**3) / Le**3
        N4 = x / Le
        N5 = (3.0 * Le * x**2 - 2.0 * x**3) / Le**3
        N6 = (-Le**2 * x**2 + Le * x**3) / Le**3
        return np.array([N1, N2, N3, N4, N5, N6], dtype=float)

    @staticmethod
    def dshape_dx(x, Le):
        dN1 = -1.0 / Le
        dN2 = (-6.0 * Le * x + 6.0 * x**2) / Le**3
        dN3 = (Le**3 - 4.0 * Le**2 * x + 3.0 * Le * x**2) / Le**3
        dN4 = 1.0 / Le
        dN5 = (6.0 * Le * x - 6.0 * x**2) / Le**3
        dN6 = (-2.0 * Le**2 * x + 3.0 * Le * x**2) / Le**3
        return np.array([dN1, dN2, dN3, dN4, dN5, dN6], dtype=float)

    @staticmethod
    def d2shape_dx2(x, Le):
        d2N1 = 0.0
        d2N2 = (-6.0 * Le + 12.0 * x) / Le**3
        d2N3 = (-4.0 * Le**2 + 6.0 * Le * x) / Le**3
        d2N4 = 0.0
        d2N5 = (6.0 * Le - 12.0 * x) / Le**3
        d2N6 = (-2.0 * Le**2 + 6.0 * Le * x) / Le**3
        return np.array([d2N1, d2N2, d2N3, d2N4, d2N5, d2N6], dtype=float)

    def Bb(self, x, Le):
        dN = self.dshape_dx(x, Le)
        return np.array([dN[0], 0.0, 0.0, dN[3], 0.0, 0.0], dtype=float)

    def Bm(self, x, Le):
        d2N = self.d2shape_dx2(x, Le)
        return np.array([0.0, d2N[1], d2N[2], 0.0, d2N[4], d2N[5]], dtype=float)

    def B_surface(self, x, Le, y):
        return self.Bb(x, Le) - y * self.Bm(x, Le)

    @staticmethod
    def gauss_1d(n=3):
        if n == 2:
            xi = np.array([-1.0 / np.sqrt(3.0), 1.0 / np.sqrt(3.0)])
            wi = np.array([1.0, 1.0])
        elif n == 3:
            xi = np.array([-np.sqrt(3.0 / 5.0), 0.0, np.sqrt(3.0 / 5.0)])
            wi = np.array([5.0 / 9.0, 8.0 / 9.0, 5.0 / 9.0])
        elif n == 4:
            xi = np.array(
                [
                    -0.8611363115940526,
                    -0.3399810435848563,
                    0.3399810435848563,
                    0.8611363115940526,
                ]
            )
            wi = np.array(
                [
                    0.3478548451374538,
                    0.6521451548625461,
                    0.6521451548625461,
                    0.3478548451374538,
                ]
            )
        else:
            raise ValueError("当前仅支持 2/3/4 点高斯积分")
        return xi, wi

    @staticmethod
    def map_to_interval(xi, a, b):
        x = 0.5 * (b - a) * xi + 0.5 * (a + b)
        jac = 0.5 * (b - a)
        return x, jac

    def element_dofs(self, e):
        n1 = e
        n2 = e + 1
        return np.array(
            [
                3 * n1 + 0,
                3 * n1 + 1,
                3 * n1 + 2,
                3 * n2 + 0,
                3 * n2 + 1,
                3 * n2 + 2,
            ],
            dtype=int,
        )

    def parse_element_measurements(self, e):
        x1 = self.node_x[e]
        x2 = self.node_x[e + 1]
        Le = x2 - x1

        edata = self.elements_sensor_data[e]
        measurements = edata.get("measurements", None)
        if measurements is None or len(measurements) == 0:
            raise ValueError(f"第 {e} 个单元没有 measurements 数据。")

        parsed_measurements = []

        for idx, m in enumerate(measurements):
            if "x" not in m or "strain" not in m:
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 缺少 x 或 strain。"
                )

            if "zone" not in m:
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 缺少 zone。"
                    "手动积分区域格式应为：'zone': [a, b]"
                )

            x_loc = float(m["x"])
            strain = float(m["strain"])
            weight = float(m.get("weight", 1.0))

            if x_loc < 0.0 or x_loc > Le:
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 的局部坐标 x={x_loc} "
                    f"超出范围 [0, {Le}]。"
                )

            zone = m["zone"]
            if (not isinstance(zone, (list, tuple))) or len(zone) != 2:
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 的 zone 必须是 [a, b] 或 (a, b)。"
                )

            a = float(zone[0])
            b = float(zone[1])

            if a < 0.0 or b < 0.0 or a > Le or b > Le:
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 的 zone={zone} "
                    f"超出单元局部范围 [0, {Le}]。"
                )

            if b <= a:
                raise ValueError(
                    f"第 {e} 个单元第 {idx} 条 measurement 的 zone={zone} 不合法，要求 b > a。"
                )

            if "y" in m and m["y"] not in ("", None):
                y = float(m["y"])
                if np.isclose(y, 0.0):
                    raise ValueError(
                        f"第 {e} 个单元第 {idx} 条 measurement 的 y=0 无法判定表面。"
                    )
            else:
                surface = m.get("surface", None)
                if surface is None:
                    raise ValueError(
                        f"第 {e} 个单元第 {idx} 条 measurement 既没有 y，也没有 surface。"
                    )
                surface = str(surface).strip().lower()
                if surface in ["top", "upper", "up", "上", "上表面"]:
                    y = +self.h
                elif surface in ["bot", "bottom", "lower", "down", "下", "下表面"]:
                    y = -self.h
                else:
                    raise ValueError(
                        f"第 {e} 个单元第 {idx} 条 measurement 的 surface 无法识别：{m.get('surface')}"
                    )

            parsed_measurements.append(
                {
                    "x": x_loc,
                    "y": y,
                    "strain": strain,
                    "weight": weight,
                    "zone": (a, b),
                }
            )

        return Le, parsed_measurements

    def element_matrices(self, e, gauss_n=3):
        Le, measurements = self.parse_element_measurements(e)

        ke = np.zeros((6, 6), dtype=float)
        fe = np.zeros(6, dtype=float)

        xis, wis = self.gauss_1d(gauss_n)

        for m in measurements:
            strain = float(m["strain"])
            weight = float(m["weight"])
            y = float(m["y"])
            a, b = m["zone"]

            for xi_g, w_g in zip(xis, wis):
                x, jac = self.map_to_interval(xi_g, a, b)
                Bp = self.B_surface(x, Le, y)

                ke += weight * np.outer(Bp, Bp) * w_g * jac
                fe += weight * Bp * strain * w_g * jac

        return ke, fe

    def assemble(self, gauss_n=3):
        self.K[:] = 0.0
        self.F[:] = 0.0

        for e in range(self.n_elems):
            ke, fe = self.element_matrices(e, gauss_n=gauss_n)
            gdofs = self.element_dofs(e)

            self.K[np.ix_(gdofs, gdofs)] += ke
            self.F[gdofs] += fe

        return self.K, self.F

    def solve(self, prescribed_dofs, gauss_n=3):
        self.assemble(gauss_n=gauss_n)

        all_dofs = np.arange(self.ndof)
        fixed = np.array(sorted(prescribed_dofs.keys()), dtype=int)

        invalid = [int(d) for d in fixed if d < 0 or d >= self.ndof]
        if invalid:
            max_valid = self.ndof - 1
            raise ValueError(
                f"边界条件自由度编号超出范围：{invalid}。当前模型共有 {self.n_nodes} 个节点，"
                f"总自由度数为 {self.ndof}，合法编号范围是 0 ~ {max_valid}。\n"
                "每个节点 3 个自由度，编号规则为：节点 i 的 u->3*i，v->3*i+1，phi->3*i+2。"
            )

        free = np.array([d for d in all_dofs if d not in fixed], dtype=int)

        U = np.zeros(self.ndof, dtype=float)
        for d, val in prescribed_dofs.items():
            U[d] = val

        Kff = self.K[np.ix_(free, free)]
        Kfc = self.K[np.ix_(free, fixed)]
        Ff = self.F[free]
        Uc = U[fixed]

        if Kff.shape[0] == 0:
            self.U = U
            return U

        Uf = np.linalg.solve(Kff, Ff - Kfc @ Uc)
        U[free] = Uf

        self.U = U
        return U

    def nodal_results(self):
        if self.U is None:
            raise RuntimeError("请先调用 solve()。")

        u = self.U[0::3]
        v = self.U[1::3]
        phi = self.U[2::3]
        return u, v, phi

    def nodal_results_table(self):
        u, v, phi = self.nodal_results()
        rows = []
        for i in range(self.n_nodes):
            rows.append(
                {
                    "节点": i,
                    "x坐标": float(self.node_x[i]),
                    "u位移": float(u[i]),
                    "v位移": float(v[i]),
                    "转角phi": float(phi[i]),
                }
            )
        return rows

    def print_nodal_table(self):
        rows = self.nodal_results_table()
        print("\n节点重构结果")
        print("-" * 68)
        print(f"{'节点':>6s} {'x坐标':>12s} {'u位移':>16s} {'v位移':>16s} {'转角phi':>16s}")
        print("-" * 68)
        for row in rows:
            print(
                f"{row['节点']:6d} {row['x坐标']:12.6f} {row['u位移']:16.6e} "
                f"{row['v位移']:16.6e} {row['转角phi']:16.6e}"
            )
        print("-" * 68)

    def evaluate_on_element(self, e, xi_points=100):
        if self.U is None:
            raise RuntimeError("请先调用 solve()。")

        x1 = self.node_x[e]
        x2 = self.node_x[e + 1]
        Le = x2 - x1
        ue = self.U[self.element_dofs(e)]

        xs_local = np.linspace(0.0, Le, xi_points)
        xs_global = x1 + xs_local
        us = np.zeros_like(xs_local)
        vs = np.zeros_like(xs_local)

        for i, x in enumerate(xs_local):
            N = self.shape_functions(x, Le)

            u_val = N[0] * ue[0] + N[3] * ue[3]
            v_val = N[1] * ue[1] + N[2] * ue[2] + N[4] * ue[4] + N[5] * ue[5]

            us[i] = u_val
            vs[i] = v_val

        return xs_global, us, vs

    def reconstruct_full_shape(self, points_per_element=100):
        if self.U is None:
            raise RuntimeError("请先调用 solve()。")

        X = []
        Ux = []
        Vy = []

        for e in range(self.n_elems):
            xg, ug, vg = self.evaluate_on_element(e, xi_points=points_per_element)

            if e > 0:
                xg = xg[1:]
                ug = ug[1:]
                vg = vg[1:]

            X.append(xg)
            Ux.append(ug)
            Vy.append(vg)

        X = np.concatenate(X)
        Ux = np.concatenate(Ux)
        Vy = np.concatenate(Vy)

        X_def = X + Ux
        Y_def = Vy

        return X, Ux, Vy, X_def, Y_def

    def evaluate_displacement_at(self, x_query):
        if self.U is None:
            raise RuntimeError("请先调用 solve()。")

        x_query = float(x_query)

        if x_query < self.node_x[0] or x_query > self.node_x[-1]:
            raise ValueError("x_query 超出梁长范围。")

        if np.isclose(x_query, self.node_x[-1]):
            e = self.n_elems - 1
        else:
            e = np.searchsorted(self.node_x, x_query, side="right") - 1

        x1 = self.node_x[e]
        x2 = self.node_x[e + 1]
        Le = x2 - x1
        xl = x_query - x1
        ue = self.U[self.element_dofs(e)]

        N = self.shape_functions(xl, Le)
        u_val = N[0] * ue[0] + N[3] * ue[3]
        v_val = N[1] * ue[1] + N[2] * ue[2] + N[4] * ue[4] + N[5] * ue[5]
        return u_val, v_val

    def evaluate_displacement_at_points(self, x_queries=None):
        if x_queries is None:
            return []

        if np.isscalar(x_queries):
            x_queries = [x_queries]

        results = []
        for xq in x_queries:
            uq, vq = self.evaluate_displacement_at(xq)
            results.append({"x": float(xq), "u": float(uq), "v": float(vq)})
        return results

    def print_displacement_queries(self, x_queries=None):
        results = self.evaluate_displacement_at_points(x_queries)

        if len(results) == 0:
            print("\n未设置重构位移查询点。")
            return

        print("\n指定位置的重构位移结果")
        print("-" * 60)
        print(f"{'序号':>6s} {'x坐标':>12s} {'u位移':>18s} {'v位移':>18s}")
        print("-" * 60)

        for i, item in enumerate(results, start=1):
            print(f"{i:6d} {item['x']:12.6f} {item['u']:18.6e} {item['v']:18.6e}")

        print("-" * 60)

    def compare_true_points(self, true_points=None):
        if true_points is None:
            return []

        if isinstance(true_points, dict):
            true_points = [true_points]

        results = []
        for i, pt in enumerate(true_points, start=1):
            x0 = float(pt["x"])
            u_true = float(pt.get("u", 0.0))
            v_true = float(pt.get("v", 0.0))
            label = pt.get("label", f"实测点{i}")

            u_rec, v_rec = self.evaluate_displacement_at(x0)

            results.append(
                {
                    "序号": i,
                    "标签": label,
                    "x": x0,
                    "u_实测": u_true,
                    "v_实测": v_true,
                    "u_重构": float(u_rec),
                    "v_重构": float(v_rec),
                    "Δu": float(u_rec - u_true),
                    "Δv": float(v_rec - v_true),
                }
            )

        return results

    def print_true_points_comparison(self, true_points=None):
        results = self.compare_true_points(true_points)

        if len(results) == 0:
            print("\n未设置实测对比点。")
            return

        print("\n实测点与重构点对比结果")
        print("-" * 126)
        print(
            f"{'序号':>4s} {'标签':>10s} {'x坐标':>10s} {'u实测':>12s} {'v实测':>12s} "
            f"{'u重构':>12s} {'v重构':>12s} {'Δu':>12s} {'Δv':>12s}"
        )
        print("-" * 126)

        for item in results:
            print(
                f"{item['序号']:4d} {item['标签']:>10s} {item['x']:10.6f} "
                f"{item['u_实测']:12.6e} {item['v_实测']:12.6e} "
                f"{item['u_重构']:12.6e} {item['v_重构']:12.6e} "
                f"{item['Δu']:12.6e} {item['Δv']:12.6e}"
            )

        print("-" * 126)

    def plot_on_axes(
        self,
        ax,
        points_per_element=100,
        true_points=None,
        show_original=True,
        show_nodes=True,
        equal_axis=False,
        title="直接表面应变矩阵法二维梁形状重构结果",
        annotate_points=True,
        connect_pairs=True,
        label_offset_scale=0.04,
        legend_loc="best",
        show_legend=True,
        y_limits=None,
    ):
        original_color = "#6b7280"
        shape_color = "#1d4ed8"
        node_face_color = "#3b82f6"
        true_face_color = "#ef4444"
        rec_face_color = "#16a34a"
        pair_line_color = "#94a3b8"

        X, _, _, X_def, Y_def = self.reconstruct_full_shape(
            points_per_element=points_per_element
        )
        u_node, v_node, _ = self.nodal_results()

        ax.clear()
        ax.set_facecolor("#fbfdff")
        ax.figure.set_facecolor("white")

        if show_original:
            ax.plot(
                self.node_x,
                np.zeros_like(self.node_x),
                linestyle=(0, (4, 3)),
                color=original_color,
                lw=1.2,
                label="原始中性层",
            )

        ax.plot(
            X_def,
            Y_def,
            color=shape_color,
            lw=2.4,
            solid_capstyle="round",
            label="重构后形状",
        )

        if show_nodes:
            ax.plot(
                self.node_x + u_node,
                v_node,
                linestyle="none",
                marker="o",
                ms=5.2,
                markerfacecolor=node_face_color,
                markeredgecolor="white",
                markeredgewidth=0.8,
                label="重构节点",
            )

        x_span = max(np.max(X_def) - np.min(X_def), 1e-6)
        y_all = np.concatenate([Y_def, np.zeros_like(self.node_x)])
        y_span = max(np.max(y_all) - np.min(y_all), 1e-6)
        dx_base = label_offset_scale * x_span
        dy_base = label_offset_scale * max(y_span, 0.02)

        if true_points is not None:
            if isinstance(true_points, dict):
                true_points = [true_points]

            first_true = True
            first_rec = True
            offset_patterns = [
                (1.0, 1.0),
                (1.0, -1.0),
                (-1.2, 1.0),
                (-1.2, -1.0),
                (1.6, 0.2),
                (-1.6, -0.2),
            ]

            for i, pt in enumerate(true_points, start=1):
                x0 = float(pt["x"])
                u0 = float(pt.get("u", 0.0))
                v0 = float(pt.get("v", 0.0))
                label_true = pt.get("label", f"实测点{i}")

                x_true = x0 + u0
                y_true = v0

                u_rec, v_rec = self.evaluate_displacement_at(x0)
                x_rec = x0 + u_rec
                y_rec = v_rec

                if first_true:
                    ax.plot(
                        [x_true],
                        [y_true],
                        linestyle="none",
                        marker="o",
                        ms=8.4,
                        markerfacecolor=true_face_color,
                        markeredgecolor="white",
                        markeredgewidth=0.9,
                        label="输入实测点",
                    )
                    first_true = False
                else:
                    ax.plot(
                        [x_true],
                        [y_true],
                        linestyle="none",
                        marker="o",
                        ms=8.4,
                        markerfacecolor=true_face_color,
                        markeredgecolor="white",
                        markeredgewidth=0.9,
                    )

                if first_rec:
                    ax.plot(
                        [x_rec],
                        [y_rec],
                        linestyle="none",
                        marker="s",
                        ms=7.0,
                        markerfacecolor=rec_face_color,
                        markeredgecolor="white",
                        markeredgewidth=0.9,
                        label="同位置重构点",
                    )
                    first_rec = False
                else:
                    ax.plot(
                        [x_rec],
                        [y_rec],
                        linestyle="none",
                        marker="s",
                        ms=7.0,
                        markerfacecolor=rec_face_color,
                        markeredgecolor="white",
                        markeredgewidth=0.9,
                    )

                if connect_pairs:
                    line_kwargs = {
                        "linestyle": (0, (2, 2)),
                        "linewidth": 1.0,
                        "color": pair_line_color,
                        "alpha": 0.75,
                    }
                    if i == 1:
                        ax.plot(
                            [x_true, x_rec],
                            [y_true, y_rec],
                            label="实测-重构差异",
                            **line_kwargs,
                        )
                    else:
                        ax.plot([x_true, x_rec], [y_true, y_rec], **line_kwargs)

                if annotate_points:
                    sx, sy = offset_patterns[(i - 1) % len(offset_patterns)]
                    dx = sx * dx_base
                    dy = sy * dy_base

                    ax.annotate(
                        label_true,
                        xy=(x_true, y_true),
                        xytext=(x_true + dx, y_true + dy),
                        textcoords="data",
                        fontsize=9,
                        color="black",
                        arrowprops={"arrowstyle": "-", "lw": 0.8, "color": "red"},
                    )
                    ax.annotate(
                        f"重构{i}",
                        xy=(x_rec, y_rec),
                        xytext=(x_rec - dx, y_rec - dy),
                        textcoords="data",
                        fontsize=9,
                        color="#111827",
                        arrowprops={"arrowstyle": "-", "lw": 0.8, "color": rec_face_color},
                    )

        ax.set_xlabel("变形后 x 坐标", color="#334155")
        ax.set_ylabel("y 坐标", color="#334155")
        ax.set_title(title, pad=10, fontsize=16, color="#0f172a", fontweight="semibold")
        ax.grid(True, linestyle=(0, (4, 4)), linewidth=0.8, color="#cbd5e1", alpha=0.65)
        ax.tick_params(colors="#334155")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#94a3b8")
        ax.spines["bottom"].set_color("#94a3b8")
        ax.spines["left"].set_linewidth(1.0)
        ax.spines["bottom"].set_linewidth(1.0)
        ax.margins(x=0.04, y=0.12)

        if y_limits is not None:
            y_min, y_max = float(y_limits[0]), float(y_limits[1])
            ax.set_ylim(y_min, y_max)

        if equal_axis:
            ax.set_aspect("equal", adjustable="datalim")

        if show_legend:
            ax.legend(loc=legend_loc)

    def plot_shape(self, **kwargs):
        try:
            import matplotlib.pyplot as plt
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "plot_shape() 需要 matplotlib，请先安装 requirements.txt 中的依赖。"
            ) from exc

        figsize = kwargs.pop("figsize", (10, 4))
        fig, ax = plt.subplots(figsize=figsize)
        self.plot_on_axes(ax, **kwargs)
        fig.tight_layout()
        plt.show()
