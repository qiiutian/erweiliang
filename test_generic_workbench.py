"""Production-window contract probes; synthetic algorithms stay test-local."""

import math
import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.path.dirname(__file__), ".mplconfig"))

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import gui_qt
from config_adapter import get_sample_config
from ifem.algorithms.base import ProjectReconstructionAlgorithm
from ifem.algorithms.beam_surface_integral import BeamSurfaceIntegralAlgorithm
from ifem.application.analysis_service import AlgorithmRegistry, AnalysisService
from ifem.domain.analysis import (
    AlgorithmCapabilities, AlgorithmMetadata, AnalysisResult, DeformationRegime,
    ReconstructionState, ResultField, RotationRepresentation, ValidationReport,
)
from ifem.domain.project import AnalysisCase, BoundaryCondition, empty_beam_project
from ifem.infrastructure import load_project, project_from_legacy_config
from ifem.modeling import PathBeamEditor
from ifem.ui.analysis_job import _RUNNING_THREADS
from test_ui_support import isolated_workspace_settings


class _WorkbenchProbe(ProjectReconstructionAlgorithm):
    """No FE formula: deterministic values exercise only wiring and contracts."""

    def __init__(self, space, regime):
        self.space = space
        self.regime = regime
        self.metadata = AlgorithmMetadata(
            identifier=f"test.workbench.{space}.{regime}",
            display_name=f"测试 {space} {regime}", version="1.0.0", contract_version="1",
        )
        representation = (
            RotationRepresentation.QUATERNION.value
            if space == "3d" and regime == DeformationRegime.LARGE.value
            else RotationRepresentation.ROTATION_VECTOR.value
        )
        self.capabilities = AlgorithmCapabilities(
            model_dimensions=(1,), modeling_spaces=(space,),
            element_families=("beam3d_line", "beam3d_curved") if space == "3d"
            else ("beam2d_euler_bernoulli", "beam2d_curved"),
            measurement_types=("surface_axial_strain",),
            geometry_kinds=("line", "circular_arc", "nurbs_curve", "parametric_curve"),
            supports_mixed_geometry=True, deformation_regimes=(regime,),
            rotation_representations=(representation,),
            result_fields=("quality",), required_result_fields=("quality",),
        )
        self.calls = 0
        self.last_request = None
        self.last_result = None
        self.failure = None
        self.native_payload = None
        self.hold = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.colliding_parameter = False

    def parameter_schema(self):
        properties = {"max_iterations": {"type": "integer", "minimum": 1, "default": 25}}
        if self.colliding_parameter:
            properties["gauss_n"] = {"type": "string", "enum": ["adaptive", "fixed"], "default": "adaptive"}
        return {"type": "object", "properties": properties, "additionalProperties": False}

    def validate_project(self, request):
        self.last_request = request
        return ValidationReport.valid()

    def solve_project(self, request, *, progress, cancellation):
        self.calls += 1
        self.last_request = request
        progress(0.25, "测试通用结果契约")
        if self.hold:
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError("测试未释放通用算法")
        cancellation.raise_if_cancelled()
        if self.failure is not None:
            raise self.failure
        project = request.project
        factor = 4 if self.regime == DeformationRegime.LARGE.value else 1
        representation = self.capabilities.rotation_representations[0]
        displacement = tuple(
            (factor * 0.01 * index, factor * -0.02 * index,
             factor * 0.03 * index if self.space == "3d" else 0.0)
            for index in range(len(project.nodes))
        )
        rotations = tuple(
            (math.cos(index * 0.005), 0.0, 0.0, math.sin(index * 0.005))
            if representation == RotationRepresentation.QUATERNION.value
            else (0.0, 0.0, index * 0.005)
            for index in range(len(project.nodes))
        )
        state = ReconstructionState(
            modeling_space=self.space, deformation_regime=request.deformation_regime,
            node_ids=tuple(node.identifier for node in project.nodes),
            reference_coordinates=tuple(node.coordinates for node in project.nodes),
            displacements=displacement,
            reference_frames=((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),) * len(project.nodes),
            element_ids=tuple(element.identifier for element in project.elements),
            connectivity=tuple(element.node_ids for element in project.elements),
            rotations=rotations, rotation_representation=representation,
            project_id=project.identifier, project_revision=project.revision,
        )
        quality = ResultField(
            identifier="quality", association="node", components=("score",),
            entity_ids=tuple(reversed(state.node_ids)),
            values=tuple((0.125 * (index + 1),) for index in reversed(range(len(state.node_ids)))),
            unit="score", coordinate_system="global",
        )
        self.last_result = AnalysisResult(
            algorithm_id=self.metadata.identifier, algorithm_version=self.metadata.version,
            native_model=self.native_payload, state=state, fields={"quality": quality},
            diagnostics=("synthetic contract probe; not an implemented FE method",),
        )
        return self.last_result


@isolated_workspace_settings
class GenericWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        for patcher in (
            patch.object(gui_qt, "apply_application_theme", return_value="graphite"),
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard),
            patch.object(QMessageBox, "critical"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.probes = {
            (space, regime.value): _WorkbenchProbe(space, regime.value)
            for space in ("2d", "3d")
            for regime in (DeformationRegime.SMALL, DeformationRegime.LARGE)
        }
        native = BeamSurfaceIntegralAlgorithm()
        self.service = AnalysisService(
            AlgorithmRegistry((native, *self.probes.values())),
            default_algorithm_id=native.metadata.identifier,
        )
        self.window = gui_qt.ReconstructionMainWindow(
            analysis_service=self.service, theme_id="graphite",
        )
        self.addCleanup(self._dispose)
        self.window.show()
        self.app.processEvents()

    def _until(self, predicate, timeout=4000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(2)
        self.assertTrue(predicate(), "通用工作台后台任务未在测试时限内完成。")

    def _dispose(self):
        self.window._close_after_analysis = False
        for probe in self.probes.values():
            probe.release.set()
        if self.window.analysis_jobs.is_running:
            self.window.cancel_reconstruction()
        self._until(lambda: not self.window.analysis_jobs.is_running)
        self._until(lambda: not _RUNNING_THREADS)
        self.window.hide()
        self.window.shutdown()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _project(self, probe, *, parameters=None):
        if probe.space == "2d":
            project = project_from_legacy_config(get_sample_config())
        else:
            project = PathBeamEditor.create_straight_beam(
                empty_beam_project(modeling_space="3d"),
                length=2.0, element_count=2, axis="z",
            )
        case = AnalysisCase(
            identifier=f"analysis-{probe.metadata.identifier}", name="通用契约测试",
            algorithm_id=probe.metadata.identifier, algorithm_version=probe.metadata.version,
            parameter_schema_version=probe.metadata.parameter_schema_version,
            parameters={"max_iterations": 11} if parameters is None else parameters,
        )
        return project.revised(analysis_cases=(case,), active_analysis_id=case.identifier)

    def _load(self, probe, *, project=None):
        project = project or self._project(probe)
        self.window._apply_project_document(project, dirty=False, status_text="已载入通用测试工程")
        self.assertTrue(self.window.run_button.isEnabled(), self.window._readiness_issues)
        self.assertFalse(self.window._readiness_issues)
        return project

    def _run(self):
        with patch.object(self.window, "_show_error") as error:
            self.window.run_reconstruction()
        error.assert_not_called()
        self.assertTrue(self.window._is_generic_result())
        self.assertIsNotNone(self.window.current_analysis_result)
        self.app.processEvents()
        return self.window.current_analysis_result

    def _start_held(self, probe):
        probe.hold = True
        self.window.start_reconstruction()
        self._until(probe.entered.is_set)
        self.assertTrue(self.window.analysis_jobs.is_running)

    def _finish(self, probe):
        probe.release.set()
        self._until(lambda: not self.window._analysis_busy)
        self.app.processEvents()

    def test_four_dimensional_regime_contracts_run_without_native_model(self):
        for (space, regime), probe in self.probes.items():
            with self.subTest(space=space, regime=regime):
                self._load(probe)
                request = self.window._prepare_workbench_request()
                self.assertTrue(request["project_only"])
                result = self._run()
                self.assertIsNone(result.native_model)
                self.assertEqual(result.state.modeling_space, space)
                self.assertEqual(result.state.deformation_regime, regime)
                self.assertEqual(probe.last_request.analysis_case_id, request["project"].active_analysis_id)
                self.assertEqual(probe.last_request.parameters["max_iterations"], 11)
                self.assertIs(self.window.result_fields_panel.result, result)
                self.assertEqual(self.window.result_fields_panel.model.rowCount(), len(result.state.node_ids))
                self.assertEqual(self.window.result_fields_panel.selector.currentData(), "quality")
                table = self.window.generic_state_table.table
                self.assertEqual(table.rowCount(), len(result.state.node_ids))
                self.assertAlmostEqual(float(table.item(1, 6).text()), result.state.displacements[1][2])
                if space == "3d" and regime == DeformationRegime.LARGE.value:
                    self.assertIn("四元数", table.horizontalHeaderItem(7).toolTip())
                    self.assertEqual(len(table.item(1, 7).text().split(",")), 4)
                self.assertIs(self.window.generic_result_view.result, result)
                self.assertTrue(self.window.generic_result_view.isVisible())
                geometry = self.window.generic_result_view.geometry
                self.assertEqual(tuple(node.entity_id for node in geometry.nodes), result.state.node_ids)
                self.assertEqual(tuple(node.position for node in geometry.nodes), result.state.deformed_coordinates)
                self.assertEqual(len(geometry.lines), len(result.state.element_ids))
                self.assertIn("离散", geometry.description)
                self.window.generic_result_view.set_field("quality")
                layer = self.window.generic_result_view.scalar_layer
                self.assertEqual(layer.identifier, "quality")
                self.assertEqual({point.entity_id for point in layer.points}, set(result.state.node_ids))
                self.assertFalse(self.window.results_stale)

    def test_opaque_native_payload_does_not_select_legacy_model_consumer(self):
        probe = self.probes[("3d", DeformationRegime.SMALL.value)]
        probe.native_payload = object()
        self._load(probe)
        result = self._run()
        self.assertIs(result.native_model, probe.native_payload)
        self.assertIs(self.window.generic_result_view.result, result)
        self.assertTrue(self.window._is_generic_result())

    def test_sync_and_background_use_same_generic_project_and_fields(self):
        probe = self.probes[("3d", DeformationRegime.LARGE.value)]
        self._load(probe)
        synchronous = self._run()
        self._start_held(probe)
        with patch.object(self.window, "_show_error") as error:
            self._finish(probe)
        error.assert_not_called()
        background = self.window.current_analysis_result
        self.assertIsNot(background, synchronous)
        self.assertEqual(background.state, synchronous.state)
        self.assertEqual(background.fields, synchronous.fields)
        self.assertTrue(self.window._is_generic_result())
        self.assertIs(self.window.generic_result_view.result, background)

    def test_missing_plugin_and_incompatible_space_never_start_jobs(self):
        probe = self.probes[("3d", DeformationRegime.SMALL.value)]
        project = self._project(probe)
        for algorithm_id in ("vendor.missing.generic", BeamSurfaceIntegralAlgorithm.metadata.identifier):
            with self.subTest(algorithm=algorithm_id):
                case = replace(project.analysis_cases[0], algorithm_id=algorithm_id,
                               algorithm_version=None, parameter_schema_version=None)
                self.window._apply_project_document(
                    project.revised(analysis_cases=(case,)), dirty=False, status_text="不可解测试",
                )
                self.assertFalse(self.window.run_button.isEnabled())
                with patch.object(self.window.analysis_jobs, "start") as start:
                    self.window.start_reconstruction()
                start.assert_not_called()
                self.assertFalse(self.window.analysis_jobs.is_running)
                self.assertEqual(probe.calls, 0)

    def test_generic_parameter_named_gauss_n_is_not_parsed_by_legacy_adapter(self):
        probe = _WorkbenchProbe("2d", DeformationRegime.SMALL.value)
        probe.colliding_parameter = True
        probe.metadata = replace(probe.metadata, identifier=probe.metadata.identifier + ".adaptive")
        self.service.registry.register(probe)
        self.probes[("2d", "adaptive")] = probe
        project = self._project(probe, parameters={"max_iterations": 9, "gauss_n": "adaptive"})
        self._load(probe, project=project)
        self._run()
        self.assertEqual(probe.last_request.parameters, {"max_iterations": 9, "gauss_n": "adaptive"})
        self.assertEqual(self.window._project_for_save().analysis_cases[0].parameters["gauss_n"], "adaptive")

    def test_spatial_parametric_geometry_reaches_plugin_without_flattening(self):
        probe = self.probes[("3d", DeformationRegime.SMALL.value)]
        path = PathBeamEditor.create_parametric_curve(
            empty_beam_project(modeling_space="3d"),
            expressions={"x": "R*cos(2*pi*t)", "y": "R*sin(2*pi*t)", "z": "H*t"},
            constants={"R": 0.5, "H": 2.0}, template="helix",
        )
        case = self._project(probe).analysis_cases[0]
        project = path.revised(analysis_cases=(case,), active_analysis_id=case.identifier)
        self._load(probe, project=project)
        self._run()
        self.assertEqual(probe.last_request.project.nodes, project.nodes)
        self.assertEqual(probe.last_request.project.elements, project.elements)
        self.assertEqual(probe.last_request.project.elements[0].geometry.kind, "parametric_curve")
        self.assertEqual(len(self.window.generic_result_view.geometry.nodes), len(project.nodes))
        self.assertIn("不代表连续曲线", self.window.generic_result_view.geometry.description)

    def test_failure_and_cancel_preserve_generic_result(self):
        probe = self.probes[("3d", DeformationRegime.SMALL.value)]
        self._load(probe)
        original = self._run()
        sequence = self.window.result_sequence
        probe.failure = ValueError("通用算法测试失败")
        self._start_held(probe)
        with patch.object(self.window, "_show_error") as error:
            self._finish(probe)
        error.assert_called_once_with(probe.failure)
        self.assertIs(self.window.current_analysis_result, original)
        self.assertIs(self.window.generic_result_view.result, original)
        self.assertEqual(self.window.result_sequence, sequence)
        probe.failure = None
        probe.entered.clear()
        probe.release.clear()
        self._start_held(probe)
        self.window.cancel_reconstruction()
        self._finish(probe)
        self.assertIs(self.window.current_analysis_result, original)
        self.assertIs(self.window.generic_result_view.result, original)
        self.assertFalse(self.window.results_stale)

    def test_generic_input_change_marks_snapshot_stale_and_discards_old_completion(self):
        probe = self.probes[("3d", DeformationRegime.SMALL.value)]
        self._load(probe)
        original = self._run()
        self._start_held(probe)
        previous_generation = self.window._analysis_generation
        self.window.analysis_setup.parameter_editor("max_iterations").setText("19")
        self.assertGreater(self.window._analysis_generation, previous_generation)
        self.assertTrue(self.window.results_stale)
        self._finish(probe)
        self.assertIs(self.window.current_analysis_result, original)
        self.assertIs(self.window.generic_result_view.result, original)
        self.assertIn("未应用", self.window.run_status_label.text())

    def test_generic_view_install_failure_restores_previous_result(self):
        probe = self.probes[("3d", DeformationRegime.SMALL.value)]
        self._load(probe)
        original = self._run()
        selected_id = original.state.node_ids[-1]
        self.window.generic_result_view.highlight_record("quality", selected_id)
        self.window.generic_result_view.set_projection("xz")
        original_set_result = self.window.generic_result_view.set_result
        attempts = []

        def fail_once(result):
            attempts.append(result)
            if len(attempts) == 1:
                raise ValueError("通用视图安装失败")
            return original_set_result(result)

        self._start_held(probe)
        with patch.object(self.window.generic_result_view, "set_result", side_effect=fail_once), \
                patch.object(self.window, "_show_error") as error:
            self._finish(probe)
        error.assert_called_once()
        self.assertIs(self.window.current_analysis_result, original)
        self.assertIs(self.window.generic_result_view.result, original)
        self.assertIs(self.window.result_fields_panel.result, original)
        self.assertTrue(self.window._is_generic_result())
        self.assertEqual(self.window.generic_result_view.selected_record, ("quality", selected_id))
        self.assertEqual(self.window.generic_result_view.projection, "xz")

    def test_state_and_field_selections_link_by_id_without_mutating_project(self):
        probe = self.probes[("3d", DeformationRegime.LARGE.value)]
        self._load(probe)
        result = self._run()
        window = self.window
        project, dirty = window.current_project_document, window.project_dirty
        state_table = window.generic_state_table.table
        state_table.setCurrentCell(1, 0)
        self.assertEqual(window.generic_result_view.selected_node, result.state.node_ids[1])
        self.assertIsNone(window.generic_result_view.field_id)

        # Node clicks reveal the actual state's row, preserving a 3D ID rather
        # than treating a row or x-coordinate as identity.
        window.focus_mode_button.setChecked(True)
        window.result_toggle.setChecked(False)
        window.generic_result_view.highlight_node(result.state.node_ids[2])
        window.generic_result_view.node_selected.emit(result.state.node_ids[2])
        self.assertFalse(window.focus_mode_button.isChecked())
        self.assertTrue(window.result_toggle.isChecked())
        self.assertIs(window.result_tabs.currentWidget(), window.generic_state_table)
        self.assertEqual(state_table.currentRow(), 2)

        # The field rows deliberately reverse node ordering.
        panel = window.result_fields_panel
        panel.table.setCurrentIndex(panel.model.index(0, 0))
        self.assertEqual(window.generic_result_view.selected_record, ("quality", result.state.node_ids[-1]))
        self.assertIsNone(window.generic_result_view.selected_node)
        window.generic_result_view.highlight_record("quality", result.state.node_ids[0])
        window.generic_result_view.record_selected.emit("quality", result.state.node_ids[0])
        self.assertIs(window.result_tabs.currentWidget(), panel)
        self.assertEqual(panel.table.currentIndex().row(), len(result.state.node_ids) - 1)
        self.assertIs(window.current_project_document, project)
        self.assertEqual(window.project_dirty, dirty)

    def test_project_switch_clears_generic_state_and_native_views(self):
        probe = self.probes[("3d", DeformationRegime.LARGE.value)]
        self._load(probe)
        self._run()
        self.window.load_sample_data(initial=True)
        self.assertIsNone(self.window.current_analysis_result)
        self.assertIsNone(self.window.generic_result_view.result)
        self.assertIsNone(self.window.result_fields_panel.result)
        self.assertFalse(self.window._is_generic_result())
        self.window.run_reconstruction()
        self.assertIsNotNone(self.window.current_model)
        self.assertIsNone(self.window.generic_result_view.result)
        self.assertFalse(self.window.generic_result_view.isVisible())
        self._load(probe)
        self.assertIsNone(self.window.current_model)
        self.assertIsNone(self.window.current_field)
        self.assertIsNone(self.window.current_result_frame)
        self.assertIsNone(self.window.current_analysis_result)
        self.assertFalse(self.window.result_link.targets)

    def test_save_reload_keeps_v7_geometry_case_and_does_not_persist_result(self):
        probe = self.probes[("3d", DeformationRegime.LARGE.value)]
        project = self._load(probe)
        result = self._run()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "generic.ifem.json"
            self.assertTrue(self.window._save_project_to(path))
            saved = load_project(path)
            self.assertEqual(saved.schema_version, 7)
            self.assertEqual(saved.nodes, project.nodes)
            self.assertEqual(saved.elements, project.elements)
            self.assertEqual(saved.boundary_conditions, project.boundary_conditions)
            self.assertEqual(saved.analysis_cases[0].algorithm_id, probe.metadata.identifier)
            self.assertNotIn("result", saved.to_dict())
            self.assertNotIn("deformation_regime", saved.to_dict()["analysis_cases"][0])
            self.assertIs(self.window.current_analysis_result, result)
            self.assertTrue(self.window.load_project_path(path))
        self.assertIsNone(self.window.current_analysis_result)
        self.assertIsNone(self.window.generic_result_view.result)
        self.assertTrue(self.window.run_button.isEnabled())

    def test_v7_boundary_interface_does_not_silently_add_three_dimensional_dofs(self):
        probe = self.probes[("3d", DeformationRegime.SMALL.value)]
        project = self._load(probe)
        self._run()
        self.assertFalse(self.window.boundary_editor.can_mutate())
        saved = self.window._project_for_save()
        self.assertEqual(saved.boundary_conditions, project.boundary_conditions)
        for dof in ("w", "rx", "ry", "rz"):
            with self.subTest(dof=dof), self.assertRaises(ValueError):
                BoundaryCondition(identifier="test-bc", node_id=project.nodes[0].identifier,
                                  dof=dof, value=0.0)

    def test_minimum_window_large_reading_keeps_controls_plot_and_table_visible(self):
        from ifem.ui.workspace_preferences import ReadingPreferences
        window = self.window
        window.set_reading_preferences(ReadingPreferences(120, "comfortable"))
        window.resize(1180, 760)
        self._load(self.probes[("3d", DeformationRegime.LARGE.value)])
        self._run()
        view, panel = window.generic_result_view, window.result_fields_panel
        view.set_field("quality")
        window.result_tabs.setCurrentWidget(panel)
        window.right_split.setSizes([500, 220])
        for _ in range(4):
            self.app.processEvents()
        self.assertFalse(window.view_toolbar.isVisible())
        self.assertTrue(window.focus_mode_button.isVisible())
        self.assertGreaterEqual(view.canvas.height(), 110)
        self.assertLess(view.description.geometry().bottom(), view.canvas.geometry().top())
        self.assertLess(view.canvas.geometry().bottom(), view.selection_label.geometry().top())
        self.assertLess(view.selection_label.geometry().bottom(), view.height())
        self.assertLess(window.plot_content_stack.geometry().bottom(), window.right_split.widget(0).height())
        self.assertGreaterEqual(panel.table.viewport().height(), panel.table.rowHeight(0))

    def test_selecting_field_clears_shape_only_node_selection(self):
        self._load(self.probes[("3d", DeformationRegime.LARGE.value)])
        result = self._run()
        view = self.window.generic_result_view
        view.highlight_node(result.state.node_ids[0])
        self.assertIsNotNone(view.selected_node)
        view.set_field("quality")
        self.assertIsNone(view.selected_node)
        self.assertEqual(self.window.generic_state_table.table.currentRow(), -1)

    def test_generic_request_does_not_parse_hidden_legacy_plot_options(self):
        for space in ("2d", "3d"):
            with self.subTest(space=space):
                self._load(self.probes[(space, DeformationRegime.SMALL.value)])
                original_view_state = dict(self.window.current_project_document.view_state)
                # An unfinished native Y-limit draft is unrelated to this method.
                self.window.y_min_edit.setText("-1")
                self.window.y_max_edit.setText("")
                self.assertTrue(self.window._refresh_input_readiness())
                request = self.window._prepare_workbench_request()
                self.assertEqual(dict(request["project"].view_state), original_view_state)
                self._run()


if __name__ == "__main__":
    unittest.main()
