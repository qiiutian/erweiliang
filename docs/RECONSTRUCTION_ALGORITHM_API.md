# iFEM 重构算法接入接口

本文档说明如何在不增加算法专用服务分支、也不修改既有二维求解公式的前提下，实现并
注册新的梁重构方法。Qt 工作台已能直接消费标准重构状态与离散字段，新公式可以
直接进入统一注册、匹配、校验、运行和基础结果显示链路；连续场插值仍由 `ANA-003` 继续完成。
当前仓库只注册了二维小变形算法；二维大变形、三维小变形和三维大变形只定义接口与
契约测试，不注册尚未实现的占位算法。

当前内置算法的用户显示名称为“局部积分 ASP-iFEM”。其稳定 ID 仍为
`ifem.beam2d.surface_integral.v1`，因此旧项目无需迁移或改绑。每个测点的
`integration_bounds` 是用户选择的 `0..1` 归一化局部积分区间，旧配置适配器会将其
转换为单元物理局部坐标中的 `zone`；`gauss_n` 只控制该区间上的 2/3/4 点数值高斯
积分，`points_per_element` 只控制后处理采样密度。

## 1. 方法能力矩阵

二维/三维表示物理建模空间，梁的拓扑维度始终是 `1`。小变形/大变形是分析意图，
不是几何属性，也不应编码到单元族名称中。

| 方法 | `modeling_spaces` | `deformation_regimes` | 常见转角表示 |
|---|---|---|---|
| 二维小变形 | `("2d",)` | `("small_deformation",)` | `rotation_vector` |
| 二维大变形 | `("2d",)` | `("large_deformation",)` | `rotation_vector` |
| 三维小变形 | `("3d",)` | `("small_deformation",)` | `rotation_vector` |
| 三维大变形 | `("3d",)` | `("large_deformation",)` | `quaternion` 或 `rotation_matrix` |

插件还必须如实声明 `element_families`、`geometry_kinds`、`measurement_types` 和
`result_fields`。尚未实现圆弧或 NURBS 公式时，不得提前把对应几何列入能力声明。

## 2. 稳定边界

重构插件只依赖 `ifem.domain`，不导入 Qt、VTK 或主窗口：

1. `AlgorithmMetadata`：稳定算法 ID、算法版本、参数模式版本和接口契约版本。
2. `AlgorithmCapabilities`：空间、变形制度、几何、单元、测量、结果和转角能力。
3. `AnalysisContext`：完整不可变 `ProjectDocument`、活动工况 ID、动态参数和变形制度。
4. `ReconstructionState`：稳定节点/单元 ID、参考坐标、位移、转角及连接关系。
5. `ResultField`：按节点、单元、测点或采样点关联的附加标量/向量/张量结果。
6. `AnalysisResult`：通用状态、字段、诊断；`native_model` 只保留给旧二维后处理兼容层。

`contract_version="0"` 是旧插件兼容模式，可继续返回原生模型和旧式字段；所有新算法必须
显式声明 `contract_version="1"` 并返回 `ReconstructionState`。接口版本与算法版本、
参数模式版本分别演进，不能互相代替。

项目版入口是 `AnalysisService.prepare_project()`、`validate_project()` 和
`run_project()`。服务层会在调用插件前完成版本、参数和模型能力校验；CLI、后台任务与
界面不能绕过这条防线。旧的 `run(config)` 只用于兼容现有二维配置入口。

重构方法由用户或项目工况显式选择，能力匹配只生成“适用/不适用”结论，不能替换用户
选择。算法应在 `validate()` / `validate_project()` 中完成自身的可解性分析；当前局部
积分方法会组装方程、检查约束后自由方程 `Kff` 是否满秩，并进行无副作用试解以确认
结果有限，但不会在校验阶段提交重构结果；组合性的测点、积分区间与边界约束问题统一以
`/analysis/solvability` 返回。条件数可以作为警告
或诊断，但不能使用与尺度无关的固定阈值直接替用户判定失败。

## 3. 新算法最小骨架

新方法继承 `ProjectReconstructionAlgorithm`，直接消费领域工程：

```python
from ifem.algorithms import ProjectReconstructionAlgorithm
from ifem.domain import (
    AlgorithmCapabilities,
    AlgorithmMetadata,
    AnalysisResult,
    DeformationRegime,
    ReconstructionState,
    RotationRepresentation,
    ValidationReport,
)


class Beam3DLargeDeformationAlgorithm(ProjectReconstructionAlgorithm):
    metadata = AlgorithmMetadata(
        identifier="vendor.beam3d.large.v1",
        display_name="三维梁大变形重构",
        version="1.0.0",
        parameter_schema_version="1",
        contract_version="1",
    )
    capabilities = AlgorithmCapabilities(
        model_dimensions=(1,),
        modeling_spaces=("3d",),
        deformation_regimes=(DeformationRegime.LARGE.value,),
        element_families=("beam3d_line",),
        geometry_kinds=("line",),
        measurement_types=("surface_axial_strain",),
        result_fields=("axial_strain",),
        rotation_representations=(RotationRepresentation.QUATERNION.value,),
        supports_mixed_geometry=False,
    )

    def parameter_schema(self):
        return {
            "type": "object",
            "properties": {
                "max_iterations": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 30,
                }
            },
        }

    def validate_project(
        self,
        request,
    ):
        # 使用稳定 JSON Pointer 返回字段级问题。
        return ValidationReport.valid()

    def solve_project(
        self,
        request,
        *,
        progress,
        cancellation,
    ):
        cancellation.raise_if_cancelled()
        project = request.project
        max_iterations = request.parameters.get("max_iterations", 30)
        # 在插件内部把 ProjectDocument 适配为本算法自己的类型化输入并求解。
        state = ReconstructionState(...)
        return AnalysisResult(
            algorithm_id=self.metadata.identifier,
            algorithm_version=self.metadata.version,
            state=state,
            fields={},
        )
```

参数模式中的 `default` 是界面建议值，不会由分析服务写入或自动注入参数。插件必须使用
`request.parameters.get(name, default)`，或把该参数列入 `required` 后自行校验，不能假设
可选键一定存在。项目绑定工况存在时，`run_project(parameters=...)` 将传入映射作为该工况
参数的覆盖项；传入 `{}` 保留工况参数。显式改用其他算法且不绑定该工况时不会继承旧算法参数。

实现完成并通过契约测试后，才把实例注册到 `AlgorithmRegistry`。不要为规划中的算法注册
会在 `solve_project()` 抛出“未实现”的占位插件。

## 4. 结果约束

- 所有坐标、位移、转角和字段值必须是有限数。
- 节点/单元/测点关联使用项目稳定 ID，不使用表格行号或临时数组序号。
- `ReconstructionState` 始终用三分量全局坐标和位移；二维结果的 `z` 分量为零。
- 坐标和位移单位统一为 m；`rotation_vector` 单位为 rad；四元数和旋转矩阵无量纲。
- 每个节点必须返回行优先的 `reference_frames`。该矩阵把局部分量映射到全局分量，
  三列分别为参考截面局部轴在全局坐标中的方向；局部 `x` 轴沿梁参考切向，`y/z`
  构成右手截面标架，矩阵必须属于 `SO(3)`。
- `rotation_vector` 表示从参考截面标架到当前截面标架的主动相对旋转，分量在全局基底
  中表达；二维 `phi` 对应全局 `+z` 右手旋转。
- `quaternion` 使用标量在前的 `(w, x, y, z)` 单位四元数，表示同一主动相对旋转；
  `q` 与 `-q` 物理等价。`rotation_matrix` 使用行优先 `3×3`，表示同一旋转且必须属于
  `SO(3)`。服务/领域层会拒绝非单位四元数和非正交、非右手矩阵。
- `ResultField.identifier` 必须出现在 `capabilities.result_fields`；字段值行数、分量数及
  实体关联由领域对象和服务层共同校验。
- `capabilities.result_fields` 表示插件可能返回的字段；只有列入
  `required_result_fields` 的字段才保证每次返回。位移、转角和变形坐标由
  `ReconstructionState` 保证，不依赖可选字段。
- `AnalysisResult.locations` 是可选的 `tuple[ResultLocation, ...]`，每条记录包含
  `association、entity_id、reference_position、position、source_entity_id、label`。
  位置统一为真实三分量坐标（m），不能包含视觉厚度放大；关联类型与 ID 的组合必须唯一。
- `map_result_field(result, field_id)` 返回独立于 `native_model` 的不可变
  `ResultFieldLayer`，包含字段标签、关联、分量、单位、坐标系及 `records`。
  每条记录包含原值、实体 ID、参考/重构位置、来源 ID 和标签。节点按 `state.node_ids`
  取位置而非字段行号；sensor/sample 必须提供显式位置，element/global 未提供位置时返回
  `None`，不猜测单元中心或模型原点。同坐标的左右单元采样不合并。
- `source_entity_id` 是来源元数据，不自动推断拓扑、插值或几何父子关系。未知字段保留插件
  声明的名称、单位和分量，不冒用内置物理语义。旧版 contract-0 任意字段载荷不会强制迁移；
  字段浏览器对不可解析载荷显示说明，不破坏旧二维原生结果视图。

### 4.1 已注册字段（2026-10-13）

| ID | 关联 | 分量 | 原始单位 |
|---|---|---|---|
| `displacement` | node / sample | x,y 或 x,y,z | m |
| `rotation` | node / sample | x,y,z；w,x,y,z；行优先 9 分量矩阵 | rad；1；1 |
| `axial_strain` | node / element / sample | axial 或 top,bottom | 1 |
| `axial_stress` | node / element / sample | axial 或 top,bottom | Pa |
| `sensor_measured_strain` | sensor | axial | 1 |
| `sensor_reconstructed_strain` | sensor | axial | 1 |
| `sensor_strain_residual` | sensor | axial | 1 |

内置字段的单位、分量、关联与坐标系（global/local）在 v1 服务返回前校验；不要求所有
算法返回全部字段。内置二维方法输出原始逐单元上下表面值，交界左右保留不同快照 ID；
无 E 时不生成应力字段，不返回全零假数据。没有工程身份的旧配置调用使用明确的快照作用域 ID。

测点残差定义为原始解在测点的 `B_surface(x, L, y) @ Ue − measured`，与用户选择的区间
积分目标不同，也不表示真实重构误差。内置算法缺测报字段级错误，合法零不受影响。
残差表将 SI 应变乘 `1e6` 显示为 με；RMS 为各已观测点的非加权均方根，不生成合格阈值。
三个字段通过实体 ID 连接，并检查坐标系和差值公式一致；不一致时不给出误导性的残差汇总。
显示连续化和采样密度不改变测点点值残差，探针保留物理位置，仅渲染标记随厚度显示倍率变化。

接口 v1 的节点和单元集合目前对应完整 `ProjectDocument`，连接关系直接使用稳定节点 ID，
不使用数组下标。几何与分析网格分离后将通过后续契约版本增加独立分析实体映射；不要在
v1 中用临时求解器序号冒充项目 ID。圆弧、公式参数曲线和 NURBS 的沿程采样、父单元
局部坐标、有限变形应变/应力度量仍属于 `ANA-003` 的完整字段模式；本轮仅标准化显式位置和
基础轴向分量，不把大变形应变自动解释为小应变，也不假设 Cauchy / Piola 应力可混用。

## 5. 三维自由度

项目 v7 的边界条件仍只允许二维名称 `u/v/phi`，现有二维适配器继续按每节点
`[u, v, phi]` 排列，数值顺序不得在接口整理中改变。真实三维算法接入项目文件前，
必须通过显式格式迁移加入 `ux/uy/uz/rx/ry/rz` 六自由度；不能在同一 v7 标记下静默
扩展允许值，否则旧版 v7 阅读器将无法可靠打开新文件。

项目 v7 不单独持久化变形制度：当前规划中的四个插件各自只声明一种制度，服务可从唯一
能力自动确定。如果某个插件同时声明小变形和大变形，调用者必须向 `prepare_project()` /
`run_project()` 显式传入 `deformation_regime`，否则服务会在进入插件前返回
`/analysis/deformation-regime` 校验错误。

## 6. 接入验收

每个真实新算法至少需要：

1. 独立插件类，不继承现有二维算法实现。
2. 2D/3D、small/large、几何、单元和测量能力匹配测试。
3. 完整 `ProjectDocument` 直通测试，覆盖稳定 ID、三维坐标、曲线参数和测点方向。
4. 动态参数模式、字段级校验、取消和进度测试。
5. `ReconstructionState` 与 `ResultField` 的形状、有限性、实体关联和声明一致性测试。
6. 算法自身的数值基准、刚体模态、边界条件、单位和病态输入测试。
7. 现有二维小变形样例位移基线不变。

通用字段注册、位置映射、字段浏览器及主工作台的标准状态/离散点绘图已经接入。
v1 新插件通过 `validate_project()` / `run_project()` 接收完整工程、活动工况、版本/模式绑定和
自己的参数；不再因非 legacy 几何被界面统一阻止。能力匹配、字段校验与插件数值校验仍必须通过。
只有内置方法与旧 contract-v0 插件使用二维兼容参数入口；`query_xs/true_points` 和旧积分默认值
不会自动注入新插件的严格参数模式，工况换方法时不混入旧方法的参数。

`native_model` 仅在其为兼容的二维梁模型时进入原绘图器；其他对象不能因非空就被当作旧求解器。
通用显示读取 `ReconstructionState` 的真实参考/重构 XYZ，将单元连接关系中的相邻分析节点连线，
不重建曲梁精确曲线或实体截面；以 Matplotlib 三维交互和 XY/XZ/YZ 投影显示，不放大变形。
`ResultField` 按明确分量与单位着色，只有已知位置的记录绘制离散点，不插值为连续云图。
无位置的单元/全局记录仍可查表和复制；自定义字段保留原名/分量/单位，不推断物理意义。
节点与字段记录通过稳定 ID 双向关联数据表，投影切换保持选择；跨实体关联的字段切换清除选择。
转动状态表直接注明向量/四元数/矩阵表示及单位，不把三维转动折算成二维 `phi`。

本切片通过测试局部插件验证二维/三维、小/大变形状态，没有注册新的生产算法。
连续场、曲线采样局部参数、有限变形应变/应力度量和 VTK 通用场仍属于 `ANA-003/ANA-004`。
项目格式保持 v7，不保存结果、图表选择或任务，也不提前扩展三维边界条件。

进度回调使用 `[0, 1]` 的非递减比例和短状态文本；长循环应定期调用
`cancellation.raise_if_cancelled()`。输入问题由 `ValidationReport` 返回稳定 JSON Pointer，
取消使用 `AnalysisCancelled`，其他求解失败保留原异常并由任务层记录诊断。

### 6.1 桌面后台执行

`AnalysisJobController.start(service, config, algorithm_id=..., parameters=..., project=...,
snapshot_key=..., project_only=False)` 复制输入后返回任务 ID。通用工作台传 `project_only=True`
并由线程调用 `run_project()`，保留完整工况绑定；旧入口默认调用 `run()`。
工作线程仅执行服务，不能调用 QWidget、Matplotlib
或 VTK；所有公开回调在控制器所属的主线程发送。
信号为 `progress(job_id, snapshot_key, fraction, message)`、
`succeeded(..., result)` / `failed(..., error)` / `cancelled(...)` 之一，随后 `finished(...)`。
消费者检查任务 ID 和工程输入代次后才能安装结果，过期或取消任务的晚到结果不得覆盖工作区。

`cancel()` 是协作请求，不强杀线程。`shutdown()` 禁止后续任务并请求取消；返回 `False`
代表必须保留事件循环至 `finished`，不能立即销毁应用。桌面入口含应用级 Quit 保护，先等待
当前数值步骤结束，再进入未保存确认。同步 `run_reconstruction()` 保留给脚本和既有测试；
真实按钮、F5、命令搜索和空态入口统一使用 `start_reconstruction()`。
