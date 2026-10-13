"""Result identities use real PyVista meshes; native rendering is not exercised."""

import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

import visualization_3d as view_module
from visualization_3d import Structure3DView
from visualization_data import BeamSectionResult, ResultFrame, StructuralModelData


class FakePlotter:
    def __init__(self, parent):
        self._closed = False
        self.interactor = QWidget(parent)
        self.camera_position = "unchanged camera"
        self.camera = SimpleNamespace(zoom=lambda value: None)
        self.actors = {}
        self.mesh_options = {}
        self.renders = 0
        self.camera_resets = 0

    def add_mesh(self, mesh, **options):
        actor = SimpleNamespace(mapper=SimpleNamespace(dataset=mesh, scalar_range=None))
        self.actors[options["name"]] = actor
        self.mesh_options[options["name"]] = options
        return actor

    def remove_actor(self, name, **options):
        self.actors.pop(name, None)

    def clear(self):
        self.actors.clear()

    def add_axes(self, **options):
        pass

    def set_background(self, *args, **options):
        pass

    def view_xy(self, **options):
        pass

    def enable_parallel_projection(self):
        pass

    def reset_camera(self, **options):
        self.camera_resets += 1

    def _render(self):
        self.renders += 1

    def close(self):
        self._closed = True


class FakePicker:
    def __init__(self, actor, data, point_id, cell_id=-1, position=(0, 0, 0)):
        self.actor, self.data, self.point_id = actor, data, point_id
        self.cell_id, self.position = cell_id, position

    def GetActor(self):
        return self.actor

    def GetDataSet(self):
        return self.data

    def GetPointId(self):
        return self.point_id

    def GetCellId(self):
        return self.cell_id

    def GetPickPosition(self):
        return self.position


@unittest.skipIf(view_module.pv is None, "PyVista mesh package unavailable")
class Result3DLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(view_module, "PYVISTA_AVAILABLE", False):
            self.view = Structure3DView()
        self.view.plotter = FakePlotter(self.view)
        self.backend_patch = patch.object(view_module, "PYVISTA_AVAILABLE", True)
        self.backend_patch.start()
        self.addCleanup(self.backend_patch.stop)
        self.addCleanup(self.view.close)
        self.model = StructuralModelData(
            [[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 1], [1, 2]], 0.2, 0.15,
        )
        x = np.array([0, .5, 1, 1, 1.5, 2.])
        section = BeamSectionResult(
            [0, 0, 0, 1, 1, 1], x,
            np.column_stack((x, .1*x*x, np.zeros(6))),
            .1*x, [-.1, 0, .1], np.arange(18).reshape(3, 6)*1e-6,
            None, "raw", 17e-6, None,
        )
        self.frame = ResultFrame(
            7, 0., [[0, 0, 0], [1, .1, 0], [2, .4, 0]],
            [[0, 0, 0], [0, .1, 0], [0, .4, 0]], section,
        )
        self.picks = []
        self.view.result_picked.connect(lambda kind, index: self.picks.append((kind, index)))
        self.view.set_frame(self.model, self.frame)

    def test_raw_mesh_point_ids_follow_fortran_order_without_merging_boundaries(self):
        for block, mesh in zip(self.view._surface_blocks, self.view._surface_meshes):
            ids = mesh.point_data[self.view._SAMPLE_ID]
            expected = np.flatnonzero(self.frame.section.element_index == block.element_index)
            for point_id, index in enumerate(ids):
                self.assertEqual(index, expected[point_id % len(expected)])
                np.testing.assert_allclose(mesh.points[point_id], block.points.reshape(-1, 3, order="F")[point_id])
        for actor, mesh, point_id in (
            (self.view._surface_actors[0], self.view._surface_meshes[0], 2),
            (self.view._surface_actors[1], self.view._surface_meshes[1], 0),
        ):
            self.assertTrue(self.view._accept_result_pick(FakePicker(actor, mesh, point_id)))
        self.assertEqual(self.picks, [("sample", 2), ("sample", 3)])
        self.assertEqual(self.frame.section.x_reference[2], self.frame.section.x_reference[3])

    def test_real_surface_extraction_and_normals_keep_sample_identity(self):
        # Same topology-changing operations used by PyVista smooth shading.
        mesh = self.view._surface_meshes[1].extract_surface(algorithm="dataset_surface")
        mesh = mesh.compute_normals(split_vertices=True)
        ids = mesh.point_data[self.view._SAMPLE_ID]
        self.assertEqual(set(ids), {3, 4, 5})
        point_id = int(np.flatnonzero(ids == 4)[-1])
        picker = FakePicker(self.view._surface_actors[1], mesh, point_id)
        self.assertTrue(self.view._accept_result_pick(picker))
        self.assertEqual(self.picks, [("sample", 4)])

    def test_cell_only_pick_uses_actual_cell_vertices_not_global_x(self):
        mesh = self.view._surface_meshes[1].extract_surface(algorithm="dataset_surface")
        cell = mesh.get_cell(0)
        point_id = cell.point_ids[-1]
        expected = int(mesh.point_data[self.view._SAMPLE_ID][point_id])
        picker = FakePicker(self.view._surface_actors[1], mesh, -1, 0, mesh.points[point_id])
        self.assertTrue(self.view._accept_result_pick(picker))
        self.assertEqual(self.picks, [("sample", expected)])

    def test_nodal_average_indices_are_direct_and_node_pick_is_separate(self):
        section = replace(self.frame.section, representation="nodal_average")
        self.view.set_frame(self.model, replace(self.frame, section=section))
        self.assertEqual(len(self.view._surface_meshes), 1)
        mesh = self.view._surface_meshes[0]
        np.testing.assert_array_equal(mesh.point_data[self.view._SAMPLE_ID][:6], np.arange(6))
        picker = FakePicker(self.view._node_actor, self.view._node_mesh, 1)
        self.assertTrue(self.view._accept_result_pick(picker))
        self.assertEqual(self.picks, [("node", 1)])

    def test_real_tube_outer_and_inner_profiles_keep_same_exact_sample_ids(self):
        model = replace(self.model, section_shape="circular_tube", section_parameters={
            "outer_diameter": .2, "wall_thickness": .02,
        })
        self.view.set_frame(model, self.frame)
        self.assertEqual(len(self.view._surface_meshes), 4)
        for index in (2, 3):
            ids = self.view._surface_meshes[index].point_data[self.view._SAMPLE_ID]
            np.testing.assert_array_equal(ids[:6], [3, 4, 5, 3, 4, 5])
        self.view.set_result_selection("sample", 4)
        self.assertEqual(len(self.view._selection_actor_names), 3)
        for name in self.view._selection_actor_names:
            self.assertFalse(self.view.plotter.mesh_options[name]["pickable"])

    def test_circle_box_and_i_section_profiles_map_each_station(self):
        profiles = (
            ("circle", {"diameter": .2}, 1),
            ("box", {"outer_height": .2, "outer_width": .1, "wall_thickness": .01}, 2),
            ("i_section", {"height": .2, "flange_width": .1,
                           "flange_thickness": .02, "web_thickness": .012}, 1),
        )
        for shape, parameters, loops in profiles:
            for representation in ("raw", "nodal_average"):
                with self.subTest(shape=shape, representation=representation):
                    model = replace(self.model, section_shape=shape, section_parameters=parameters)
                    frame = replace(self.frame, section=replace(self.frame.section, representation=representation))
                    self.view.set_frame(model, frame)
                    self.assertEqual(len(self.view._surface_blocks), loops * (2 if representation == "raw" else 1))
                    for block, mesh in zip(self.view._surface_blocks, self.view._surface_meshes):
                        ids = self.view._block_sample_indices(block)
                        np.testing.assert_array_equal(mesh.point_data[self.view._SAMPLE_ID],
                                                      np.tile(ids, block.points.shape[1]))
                    self.view.set_result_selection("sample", 4)
                    self.assertEqual(len(self.view._selection_actor_names), loops + 1)

    def test_selection_survives_mode_thickness_scene_and_theme_without_camera_reset(self):
        self.view.set_result_selection("sample", 4)
        camera = self.view.plotter.camera_position
        resets = self.view.plotter.camera_resets
        self.view.set_frame(self.model, self.frame, mode="strain", thickness_scale=3.)
        self.view.show_original_check.setChecked(False)
        self.view.apply_theme("graphite")
        self.assertEqual(self.view._result_selection, ("sample", 4))
        self.assertEqual(self.view.plotter.camera_position, camera)
        self.assertEqual(self.view.plotter.camera_resets, resets)
        marker = self.view.plotter.actors["result-selection-point"].mapper.dataset
        np.testing.assert_allclose(marker.points[0], self.frame.section.centerline_deformed[4])
        station = self.view.plotter.actors["result-selection-station-1"].mapper.dataset
        self.assertGreater(np.ptp(station.points[:, 1]), .5)

    def test_external_probe_has_exact_position_and_mutually_exclusive_selection(self):
        self.view.set_probe_position((.345, .456, .567))
        self.assertIsNone(self.view._result_selection)
        point = self.view.plotter.actors["result-selection-point"].mapper.dataset.points[0]
        np.testing.assert_allclose(point, [.345, .456, .567])
        self.view.set_frame(self.model, self.frame, mode="stress", thickness_scale=2.)
        self.assertEqual(self.view._probe_position, (.345, .456, .567))
        self.view.set_result_selection("node", 1)
        self.assertIsNone(self.view._probe_position)
        self.assertEqual(self.view._result_selection, ("node", 1))

    def test_new_sequence_clear_and_shutdown_remove_selection_without_late_render(self):
        self.view.set_result_selection("sample", 2)
        self.view.set_frame(self.model, replace(self.frame, sequence=8))
        self.assertIsNone(self.view._result_selection)
        self.assertFalse(self.view._selection_actor_names)
        self.view.set_probe_position((0, 1, 2))
        self.view.clear_frame()
        self.assertIsNone(self.view._probe_position)
        self.view.set_frame(self.model, self.frame)
        self.view.set_result_selection("node", 1)
        self.view.shutdown()
        renders = self.view.plotter.renders
        self.view.set_result_selection("sample", 0)
        self.view.set_probe_position((0, 0, 0))
        self.view.set_frame(self.model, self.frame)
        self.view.clear_frame()
        self.assertEqual(self.view.plotter.renders, renders)
        self.assertIsNone(self.view._result_selection)
        self.assertIsNone(self.view._probe_position)

    def test_invalid_input_and_reference_or_highlight_picks_are_ignored(self):
        for kind, index in (("sample", -1), ("sample", 1000), ("node", True), ("node", 1.2), ("unknown", 0)):
            self.view.set_result_selection(kind, index)
            self.assertIsNone(self.view._result_selection)
        for position in ((0, 1), (float("nan"), 0, 0), "invalid"):
            self.view.set_probe_position(position)
            self.assertIsNone(self.view._probe_position)
        actor = self.view.plotter.actors["reference-centerline"]
        self.assertFalse(self.view._accept_result_pick(FakePicker(actor, self.view._node_mesh, 1)))
        self.assertFalse(self.view.plotter.mesh_options["reference-centerline"]["pickable"])
        self.assertFalse(self.picks)

    def test_plain_mouse_navigation_is_not_intercepted_ctrl_click_is(self):
        widget = self.view.plotter.interactor
        def event(kind, x, modifiers=Qt.KeyboardModifier.NoModifier):
            return QMouseEvent(kind, QPointF(x, 10), QPointF(x, 10),
                              Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, modifiers)
        press, release = QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease
        self.assertFalse(self.view.eventFilter(widget, event(press, 10)))
        with patch.object(self.view, "_pick_at_position") as pick:
            self.assertTrue(self.view.eventFilter(widget, event(press, 10, Qt.KeyboardModifier.ControlModifier)))
            self.assertTrue(self.view.eventFilter(widget, event(release, 11)))
            pick.assert_called_once_with(QPointF(11, 10))
            pick.reset_mock()
            self.view.eventFilter(widget, event(press, 10, Qt.KeyboardModifier.ControlModifier))
            self.view.eventFilter(widget, event(release, 40))
            pick.assert_not_called()


if __name__ == "__main__":
    unittest.main()
