from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ifem.application.analysis_service import DEFAULT_ALGORITHM_ID
from ifem.domain.analysis import (
    AlgorithmCapabilities,
    AlgorithmMetadata,
    AnalysisContext,
    AnalysisResult,
    CancellationToken,
    InputValidationError,
    ProgressReporter,
    ValidationReport,
)
from reconstruction import IBeam3SurfaceIntegralReconstruction2D


class BeamSurfaceIntegralAlgorithm:
    metadata = AlgorithmMetadata(
        identifier=DEFAULT_ALGORITHM_ID,
        display_name="积分型表面应变矩阵",
        version="1.0.0",
        description="二维 Euler-Bernoulli 梁直接表面应变积分重构。",
        parameter_schema_version="1",
    )
    capabilities = AlgorithmCapabilities(
        model_dimensions=(1,),
        element_families=("beam2d_euler_bernoulli",),
        measurement_types=("surface_axial_strain",),
        result_fields=("displacement", "rotation", "axial_strain", "axial_stress"),
        supports_transient=False,
        modeling_spaces=("2d",),
        geometry_kinds=("line",),
        supports_mixed_geometry=False,
    )

    def assess_project(self, project) -> ValidationReport:
        from ifem.modeling.path_editor import PathBeamEditor

        capability = PathBeamEditor.capability(project)
        if capability.legacy_solver_compatible:
            return ValidationReport.valid()
        return ValidationReport.invalid(capability.reason)

    def parameter_schema(self) -> Mapping[str, Any]:
        return {
            "type": "object",
            "properties": {
                "gauss_n": {
                    "type": "integer",
                    "title": "高斯点数",
                    "enum": [2, 3, 4],
                    "default": 3,
                },
                "points_per_element": {
                    "type": "integer",
                    "title": "每单元采样点数",
                    "minimum": 2,
                    "default": 120,
                },
            },
        }

    def validate(self, context: AnalysisContext) -> ValidationReport:
        # Kept as a local import while the legacy configuration module is migrated.
        from config_adapter import validate_config

        try:
            validate_config(context.project_config)
        except InputValidationError as exc:
            return ValidationReport.invalid(str(exc), field=exc.field)
        except (KeyError, TypeError, ValueError) as exc:
            return ValidationReport.invalid(str(exc))
        return ValidationReport.valid()

    def solve(
        self,
        context: AnalysisContext,
        *,
        progress: ProgressReporter,
        cancellation: CancellationToken,
    ) -> AnalysisResult:
        # The adapter delegates to the existing solver without changing its formulas.
        from config_adapter import build_model_inputs

        config = dict(context.project_config)
        for name in self.parameter_schema().get("properties", {}):
            if name in context.parameters:
                config[name] = context.parameters[name]
        inputs = build_model_inputs(config)
        progress(0.15, "正在创建二维梁模型")
        cancellation.raise_if_cancelled()

        model = IBeam3SurfaceIntegralReconstruction2D(
            node_x=inputs["node_x"],
            thickness=inputs["thickness"],
            elements_sensor_data=inputs["elements_sensor_data"],
        )
        progress(0.35, "正在组装逆有限元方程")
        cancellation.raise_if_cancelled()

        model.solve(
            prescribed_dofs=inputs["prescribed_dofs"],
            gauss_n=inputs["gauss_n"],
        )
        progress(0.9, "二维梁重构求解完成")
        cancellation.raise_if_cancelled()

        return AnalysisResult(
            algorithm_id=self.metadata.identifier,
            algorithm_version=self.metadata.version,
            native_model=model,
            inputs=inputs,
            diagnostics=("legacy_config_adapter",),
        )
