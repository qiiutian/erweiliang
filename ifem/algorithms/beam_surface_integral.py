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
    DeformationRegime,
    InputValidationError,
    ProgressReporter,
    ReconstructionState,
    RotationRepresentation,
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
        contract_version="1",
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
        deformation_regimes=(DeformationRegime.SMALL.value,),
        rotation_representations=(RotationRepresentation.ROTATION_VECTOR.value,),
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
            validate_config(self._legacy_config(context))
        except InputValidationError as exc:
            return ValidationReport.invalid(str(exc), field=exc.field)
        except (KeyError, TypeError, ValueError) as exc:
            return ValidationReport.invalid(str(exc))
        return ValidationReport.valid()

    @staticmethod
    def _legacy_config(context: AnalysisContext) -> dict[str, Any]:
        if context.project is not None:
            from ifem.infrastructure.legacy_project import legacy_config_from_project

            config = legacy_config_from_project(
                context.project,
                include_analysis_parameters=False,
            )
        elif context.project_config:
            config = dict(context.project_config)
        else:
            raise InputValidationError("当前二维算法缺少工程输入。", field="/model")
        for name in ("gauss_n", "points_per_element", "query_xs", "true_points"):
            if name in context.parameters:
                config[name] = context.parameters[name]
        return config

    @staticmethod
    def _result_state(context: AnalysisContext, model) -> ReconstructionState:
        project = context.project
        if project is None:
            node_ids = tuple(f"node-{index}" for index in range(model.n_nodes))
            element_ids = tuple(f"element-{index}" for index in range(model.n_elems))
            connectivity = tuple(
                (node_ids[index], node_ids[index + 1])
                for index in range(model.n_elems)
            )
        else:
            from ifem.modeling.path_editor import PathBeamEditor

            ordered_nodes = tuple(PathBeamEditor.ordered_nodes(project))
            node_ids = tuple(node.identifier for node in ordered_nodes)
            element_by_pair = {
                frozenset(element.node_ids): element for element in project.elements
            }
            ordered_elements = tuple(
                element_by_pair[frozenset((left.identifier, right.identifier))]
                for left, right in zip(ordered_nodes, ordered_nodes[1:])
            )
            element_ids = tuple(element.identifier for element in ordered_elements)
            connectivity = tuple(element.node_ids for element in ordered_elements)
        reference_coordinates = tuple(
            (float(value), 0.0, 0.0) for value in model.node_x
        )
        displacements = tuple(
            (float(model.U[3 * index]), float(model.U[3 * index + 1]), 0.0)
            for index in range(model.n_nodes)
        )
        rotations = tuple(
            (0.0, 0.0, float(model.U[3 * index + 2]))
            for index in range(model.n_nodes)
        )
        return ReconstructionState(
            modeling_space="2d",
            deformation_regime=DeformationRegime.SMALL.value,
            node_ids=node_ids,
            reference_coordinates=reference_coordinates,
            displacements=displacements,
            reference_frames=(
                (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
            )
            * model.n_nodes,
            element_ids=element_ids,
            connectivity=connectivity,
            rotations=rotations,
            rotation_representation=RotationRepresentation.ROTATION_VECTOR.value,
            project_id=None if project is None else project.identifier,
            project_revision=None if project is None else project.revision,
        )

    def solve(
        self,
        context: AnalysisContext,
        *,
        progress: ProgressReporter,
        cancellation: CancellationToken,
    ) -> AnalysisResult:
        # The adapter delegates to the existing solver without changing its formulas.
        from config_adapter import build_model_inputs

        config = self._legacy_config(context)
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
            state=self._result_state(context, model),
            diagnostics=("legacy_config_adapter",),
        )
