import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.join(os.path.dirname(__file__), ".mplconfig"),
)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox

import gui_qt
from ifem.domain.project import empty_beam_project
from ifem.infrastructure.project_io import load_project, save_project
from ifem.infrastructure.project_library import (
    PROJECT_LIBRARY_ENV,
    ProjectLibrary,
    default_project_library_root,
    normalize_project_name,
)
from ifem.ui.project_library import ProjectLibraryDialog, ProjectNameDialog
from ifem.ui.modeler import BeamModelerDialog
from test_ui_support import isolated_workspace_settings


@isolated_workspace_settings
class ProjectLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_root_can_be_overridden_and_names_stay_inside_library(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {PROJECT_LIBRARY_ENV: directory},
        ):
            self.assertEqual(default_project_library_root(), Path(directory).resolve())
            library = ProjectLibrary()
            self.assertEqual(
                library.path_for_name("桥梁监测"),
                Path(directory).resolve() / "桥梁监测.ifemproj",
            )

        self.assertEqual(normalize_project_name(" 项目 A.ifemproj "), "项目 A")
        for invalid in ("", "../outside", "bad/name", "name?", "CON"):
            with self.subTest(name=invalid), self.assertRaises(ValueError):
                normalize_project_name(invalid)

    def test_library_lists_valid_and_damaged_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            library = ProjectLibrary(directory)
            valid_path = library.path_for_name("二维梁")
            save_project(valid_path, empty_beam_project(name="二维梁"))
            damaged_path = library.path_for_name("损坏项目")
            damaged_path.write_text("not-json", encoding="utf-8")

            entries = library.entries()

        self.assertEqual({entry.path.name for entry in entries}, {
            "二维梁.ifemproj",
            "损坏项目.ifemproj",
        })
        valid = next(entry for entry in entries if entry.path.name == valid_path.name)
        damaged = next(
            entry for entry in entries if entry.path.name == damaged_path.name
        )
        self.assertTrue(valid.valid)
        self.assertEqual(valid.node_count, 2)
        self.assertFalse(damaged.valid)
        self.assertTrue(damaged.error)

    def test_name_dialog_validates_duplicates_and_resolves_target_path(self):
        with tempfile.TemporaryDirectory() as directory:
            library = ProjectLibrary(directory)
            existing = library.path_for_name("已有项目")
            save_project(existing, empty_beam_project(name="已有项目"))
            dialog = ProjectNameDialog(library=library)

            dialog.name_edit.setText("已有项目")
            self.assertFalse(dialog.confirm_button.isEnabled())
            self.assertIn("已存在", dialog.status_label.text())

            dialog.name_edit.setText("新项目")
            self.assertTrue(dialog.confirm_button.isEnabled())
            self.assertEqual(dialog.project_name, "新项目")
            self.assertEqual(dialog.project_path, library.path_for_name("新项目"))
            self.assertEqual(dialog.path_edit.text(), str(library.root))
            self.assertIn("新项目.ifemproj", dialog.status_label.text())
            dialog.close()

    def test_project_browser_selects_a_library_record(self):
        with tempfile.TemporaryDirectory() as directory:
            library = ProjectLibrary(directory)
            path = library.path_for_name("待打开项目")
            save_project(path, empty_beam_project(name="待打开项目"))
            dialog = ProjectLibraryDialog(library=library)
            dialog.show()
            self.app.processEvents()

            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertTrue(dialog.open_button.isEnabled())
            dialog._open_selected()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selected_path, path)
            dialog.close()

    def test_project_browser_search_and_damaged_state_are_keyboard_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            library = ProjectLibrary(directory)
            save_project(
                library.path_for_name("可用项目"),
                empty_beam_project(name="可用项目"),
            )
            damaged_path = library.path_for_name("损坏项目")
            damaged_path.write_text("not-json", encoding="utf-8")
            dialog = ProjectLibraryDialog(library=library)
            dialog.show()
            self.app.processEvents()

            self.assertEqual(dialog.search_action.shortcut().toString(), "Ctrl+F")
            dialog.search_action.trigger()
            self.assertTrue(dialog.search_edit.hasFocus())
            dialog.search_edit.setText("不存在")
            self.assertIn("0 / 2", dialog.count_label.text())
            self.assertIn("清除搜索", dialog.empty_label.text())

            QTest.keyClick(dialog.search_edit, Qt.Key.Key_Escape)
            self.assertEqual(dialog.search_edit.text(), "")
            self.assertEqual(dialog.result(), 0)

            damaged_item = next(
                dialog.tree.topLevelItem(index)
                for index in range(dialog.tree.topLevelItemCount())
                if dialog.tree.topLevelItem(index).text(0) == "损坏项目"
            )
            dialog.tree.setCurrentItem(damaged_item)
            self.assertIn("无法读取", dialog.selection_feedback_label.text())
            self.assertTrue(dialog.selection_feedback_label.wordWrap())
            self.assertFalse(dialog.selection_feedback_label.isHidden())
            self.assertTrue(
                dialog.selection_feedback_label.textInteractionFlags()
                & Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self.assertFalse(dialog.open_button.isEnabled())
            dialog.close()

    def test_project_search_selects_and_opens_the_unique_visible_result(self):
        with tempfile.TemporaryDirectory() as directory:
            library = ProjectLibrary(directory)
            expected_path = library.path_for_name("甲项目")
            save_project(expected_path, empty_beam_project(name="甲项目"))
            save_project(
                library.path_for_name("乙项目"),
                empty_beam_project(name="乙项目"),
            )
            dialog = ProjectLibraryDialog(library=library)
            dialog.show()
            dialog.search_edit.setText("甲项目")
            self.app.processEvents()

            self.assertEqual(dialog.tree.currentItem().text(0), "甲项目")
            self.assertTrue(dialog.open_button.isEnabled())
            QTest.keyClick(dialog.search_edit, Qt.Key.Key_Return)
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selected_path, expected_path)
            dialog.close()

    def test_project_name_dialog_has_visible_label_and_default_action(self):
        with tempfile.TemporaryDirectory() as directory:
            dialog = ProjectNameDialog(library=ProjectLibrary(directory))
            labels = [
                label
                for label in dialog.findChildren(QLabel)
                if label.text() == "项目名称"
            ]

            self.assertEqual(len(labels), 1)
            self.assertIs(labels[0].buddy(), dialog.name_edit)
            self.assertTrue(dialog.confirm_button.isDefault())
            dialog.name_edit.setText("桥梁项目")
            self.assertIn("可保存为", dialog.status_label.text())
            dialog.close()

    def test_main_window_save_as_uses_name_and_managed_path(self):
        with tempfile.TemporaryDirectory() as directory:
            library = ProjectLibrary(directory)
            path = library.path_for_name("命名项目")
            window = gui_qt.ReconstructionMainWindow(project_library=library)
            with patch.object(
                gui_qt.ProjectNameDialog,
                "choose_project_name",
                return_value=("命名项目", path),
            ):
                self.assertTrue(window.save_project_as())

            self.assertEqual(window.current_project_path, path)
            self.assertEqual(load_project(path).name, "命名项目")
            self.assertFalse(window.project_dirty)
            window.close()

    def test_main_window_open_uses_library_browser_result(self):
        with tempfile.TemporaryDirectory() as directory:
            library = ProjectLibrary(directory)
            path = library.path_for_name("库中项目")
            save_project(path, empty_beam_project(name="库中项目"))
            window = gui_qt.ReconstructionMainWindow(project_library=library)

            with patch.object(
                gui_qt.ProjectLibraryDialog,
                "choose_project",
                return_value=path,
            ):
                self.assertTrue(window.open_project())

            self.assertEqual(window.current_project_path, path)
            self.assertEqual(window.current_project_document.name, "库中项目")
            window.close()

    def test_new_project_reserves_the_named_library_path(self):
        with tempfile.TemporaryDirectory() as directory:
            library = ProjectLibrary(directory)
            path = library.path_for_name("新建空间梁")

            class AcceptedModeler:
                def __init__(self, project, _parent=None):
                    self.project = project
                    self.project_path = None
                    self.project_is_saved = False

                def set_project_storage(
                    self,
                    _library,
                    project_path,
                    *,
                    project_is_saved=False,
                ):
                    self.project_path = project_path

                def exec(self):
                    return QDialog.DialogCode.Accepted

            window = gui_qt.ReconstructionMainWindow(project_library=library)
            with patch.object(
                gui_qt.ProjectNameDialog,
                "choose_project_name",
                return_value=("新建空间梁", path),
            ), patch.object(gui_qt, "BeamModelerDialog", AcceptedModeler):
                self.assertTrue(window.new_project())

            self.assertEqual(window.current_project_document.name, "新建空间梁")
            self.assertEqual(window.current_project_path, path)
            self.assertTrue(window.project_dirty)
            window.project_dirty = False
            window.close()

    def test_modeler_first_save_uses_project_name_dialog_and_library(self):
        with tempfile.TemporaryDirectory() as directory:
            library = ProjectLibrary(directory)
            path = library.path_for_name("建模器项目")
            dialog = BeamModelerDialog(empty_beam_project())
            dialog.set_project_storage(library)

            with patch.object(
                ProjectNameDialog,
                "choose_project_name",
                return_value=("建模器项目", path),
            ):
                dialog._save_project()

            self.assertEqual(dialog.project.name, "建模器项目")
            self.assertEqual(dialog.project_path, path)
            self.assertTrue(dialog.project_is_saved)
            self.assertEqual(load_project(path).name, "建模器项目")
            # Naming/saving changes the document but does not apply it back to
            # the workspace. Explicitly discard that pending application.
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard,
            ) as question:
                dialog.close()
            question.assert_called_once()
            self.assertEqual(load_project(path).name, "建模器项目")


if __name__ == "__main__":
    unittest.main()
