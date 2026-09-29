"""Keep legacy UI tests independent of local workspace preferences."""

from functools import wraps
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QSettings


def isolated_workspace_settings(test_class):
    """Give each default preferences store a fresh temporary INI file.

    Register cleanup before the original setup so windows and dialogs are
    disposed while both the settings patch and its directory still exist.
    Tests that need persistence across windows should inject a shared store.
    """
    original_set_up = test_class.setUp

    @wraps(original_set_up)
    def set_up(self):
        directory = TemporaryDirectory(prefix="ifem-ui-preferences-")
        self.addCleanup(directory.cleanup)
        sequence = count()

        def fresh_settings():
            path = Path(directory.name) / f"workspace-{next(sequence)}.ini"
            return QSettings(str(path), QSettings.Format.IniFormat)

        settings_patch = patch(
            "ifem.ui.workspace_preferences._default_settings",
            side_effect=fresh_settings,
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        original_set_up(self)

    test_class.setUp = set_up
    return test_class
