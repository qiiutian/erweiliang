# iFEM 重构算法接入接口

本文档说明如何在不增加算法专用服务分支、也不修改既有二维求解公式的前提下，实现并
注册新的梁重构方法。Qt 的通用结果图层仍由 `ANA-003` 收口；本接口先保证新公式可以
直接进入统一注册、匹配、校验和运行链路。
当前仓库只注册了二维小变形算法；二维大变形、三维小变形和三维大变形只定义接口与
契约测试，不注册尚未实现的占位算法。

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
- 应变/应力场应在后续字段模式中继续声明坐标系、应变/应力度量和采样位置；不要把
  求解器私有对象作为新界面的数据协议。

接口 v1 的节点和单元集合目前对应完整 `ProjectDocument`，连接关系直接使用稳定节点 ID，
不使用数组下标。几何与分析网格分离后将通过后续契约版本增加独立分析实体映射；不要在
v1 中用临时求解器序号冒充项目 ID。圆弧/NURBS 的沿程采样、父单元局部坐标、应变/应力
度量和表面位置属于 `ANA-003` 的完整字段模式，本版不以不透明数组提前固化。

## 5. 三维自由度

项目 v6 的边界条件仍只允许二维名称 `u/v/phi`，现有二维适配器继续按每节点
`[u, v, phi]` 排列，数值顺序不得在接口整理中改变。真实三维算法接入项目文件前，
必须通过显式格式迁移加入 `ux/uy/uz/rx/ry/rz` 六自由度；不能在同一 v6 标记下静默
扩展允许值，否则旧版 v6 阅读器将无法可靠打开新文件。

项目 v6 不单独持久化变形制度：当前规划中的四个插件各自只声明一种制度，服务可从唯一
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

通用应变/应力图层和结果探针仍由 `ANA-003/ANA-004` 完成；新算法可以先通过统一服务
返回标准状态与字段，界面映射不应再反向要求它模仿旧二维 `native_model`。
当前主工作台仍以旧二维结果消费者为主，并会阻止非 legacy 几何直接运行；因此“直接接入”
在本切片中明确指 `AlgorithmRegistry + AnalysisService`。真实新算法进入桌面界面前，还需
完成通用 readiness/result consumer，这属于 `ANA-003`，不是新算法公式类的专用分支。

进度回调使用 `[0, 1]` 的非递减比例和短状态文本；长循环应定期调用
`cancellation.raise_if_cancelled()`。输入问题由 `ValidationReport` 返回稳定 JSON Pointer，
取消使用 `AnalysisCancelled`，其他求解失败保留原异常并由任务层记录诊断。
