# -*- encoding: utf-8 -*-

import os
import sys

from pathlib import Path
from typing import Optional, List, Union

# MO2 ships with PyQt5, so you can use it in your plugins:
from PyQt5.QtWidgets import QApplication
from PyQt5 import QtWidgets

import mobase

from wizard.runner import WizardRunnerState

from .dialog import WizardInstallerDialog
from .runner import make_interpreter


class WizardInstaller(mobase.IPluginInstallerSimple):

    """
    This is the actual plugin. MO2 has two types of installer plugin, this one is
    "simple", i.e., it will work directly on the file-tree contained in the archive.
    The purpose of the installer is to take the file-tree from the archive, check if
    it is valid (for this installer) and then modify it if required before extraction.
    """

    _organizer: mobase.IOrganizer

    def __init__(self):
        super().__init__()

    # Method for IPlugin - I will not details these here since those are quite
    # self-explanatory and are common to all plugins:

    def init(self, organizer: mobase.IOrganizer):
        self._organizer = organizer
        return True

    def name(self):
        return "BAIN Wizard Installer"

    def author(self):
        return "Holt59"

    def description(self):
        return self._tr("Installer for BAIN archive containing wizard scripts.")

    def version(self):
        return mobase.VersionInfo(1, 0, 0, mobase.ReleaseType.BETA)

    def isActive(self):
        return self._organizer.pluginSetting(self.name(), "enabled")

    def settings(self):
        return [
            mobase.PluginSetting("enabled", "check to enable this plugin", True),
            # TODO: I think this should be below FOMOD and above OMOD but this is
            # currently not possible since OMOD has a priority of 500...
            mobase.PluginSetting("priority", "priority of this installer", 80),
        ]

    # Method for IPluginInstallerSimple:

    def priority(self):
        return self._organizer.pluginSetting(self.name(), "priority")

    def isManualInstaller(self) -> bool:
        return False

    def onInstallationStart(
        self, archive: str, reinstallation: bool, mod: Optional[mobase.IModInterface]
    ):
        # TODO: Reload choices.
        pass

    def onInstallationEnd(
        self, result: mobase.InstallResult, mod: Optional[mobase.IModInterface]
    ):
        # TODO: Save choices.
        pass

    def _getWizardArchiveBase(
        self, tree: mobase.IFileTree, data_name: str, checker: mobase.ModDataChecker
    ) -> Optional[mobase.IFileTree]:
        """
        Try to find the folder containing wizard.txt.

        Args:
            tree: Tree to look the data folder in.
            data_name: Name of the data folder (e.g., "data" for Bethesda games).
            checker: Checker to use to check if a tree is a data folder.

        Returns:
            The tree corresponding to the folder containing wizard.txt, or None.
        """

        entry = tree.find("wizard.txt", mobase.FileTreeEntry.FILE)

        if entry:
            return tree

        if len(tree) == 1 and isinstance(tree[0], mobase.IFileTree):
            return self._getWizardArchiveBase(tree[0], data_name, checker)

        return None

    def _getImageEntries(
        self,
        tree: mobase.IFileTree,
        extensions: List[str] = ["png", "jpg", "jpeg", "gif", "bmp"],
    ) -> List[mobase.FileTreeEntry]:
        """
        Retrieve all the entries corresponding to images in the given tree.

        Args:
            tree: The tree containing the images.
            extensions: The extensions for images.

        Returns:
            A list of entries corresponding to files with the given extensions.
        """
        entries = []

        def fn(path: str, entry: mobase.FileTreeEntry):
            if entry.isFile() and entry.hasSuffix(extensions):
                entries.append(entry)
            return mobase.IFileTree.CONTINUE

        tree.walk(fn)

        return entries

    def isArchiveSupported(self, tree: mobase.IFileTree) -> bool:
        """
        Check if the given file-tree (from the archive) can be installed by this
        installer.

        Args:
            tree: The tree to check.

        Returns:
            True if the file-tree can be installed, false otherwise.
        """

        # Retrieve the name of the "data" folder:
        data_name = self._organizer.managedGame().dataDirectory().dirName()

        # Retrieve the mod-data-checker:
        checker: mobase.ModDataChecker = self._organizer.managedGame().feature(
            mobase.ModDataChecker  # type: ignore
        )

        # Do the actual check - Convert to bool or do `is not None` to avoid
        # issue with Python > C++ conversion:
        return bool(self._getWizardArchiveBase(tree, data_name, checker))

    def install(
        self,
        name: mobase.GuessedString,
        otree: mobase.IFileTree,
        version: str,
        modId: int,
    ) -> Union[mobase.InstallResult, mobase.IFileTree]:
        """
        Perform the actual installation.

        Args:
            name: The "name" of the mod. This can be updated to change the name of the
                mod.
            otree: The original archive tree.
            version: The original version of the mod.
            modId: The original ID of the mod.

        Returns: We either return the modified file-tree (if the installation was
            successful), or a InstallResult otherwise.

        Note: It is also possible to return a tuple (InstallResult, IFileTree, str, int)
            containing where the two last members correspond to the new version and ID
            of the mod, in case those were updated by the installer.
        """

        # Retrieve the name of the "data" folder:
        data_name = self._organizer.managedGame().dataDirectory().dirName()

        # Retrieve the mod-data-checker:
        checker: mobase.ModDataChecker = self._organizer.managedGame().feature(
            mobase.ModDataChecker  # type: ignore
        )

        # Retrive the "base" folder:
        base = self._getWizardArchiveBase(otree, data_name, checker)
        if not base or not checker:
            return mobase.InstallResult.NOT_ATTEMPTED

        wizard = base.find("wizard.txt")
        if wizard is None:
            return mobase.InstallResult.NOT_ATTEMPTED

        images = self._getImageEntries(otree)

        # Extract the script:
        # TODO: Extract pictures, similar to the FOMOD installer.
        paths = self._manager().extractFiles([wizard] + images, silent=False)
        if len(paths) != len(images) + 1:
            return mobase.InstallResult.FAILED

        interpreter = make_interpreter(base, self._organizer)

        script = paths[0]

        dialog = WizardInstallerDialog(
            self._organizer,
            interpreter,
            interpreter.make_top_level_context(Path(script), WizardRunnerState()),
            name,
            {Path(entry.path()): Path(path) for entry, path in zip(images, paths[1:])},
            self._parentWidget(),
        )

        dialog.scriptButtonClicked.connect(lambda: os.startfile(script))

        # Note: Unlike the official installer, we do not have a "silent" setting,
        # but it is really simple to add it.
        if dialog.exec() == QtWidgets.QDialog.Accepted:

            # We update the name with the user specified one:
            name.update(dialog.name(), mobase.GuessQuality.USER)

            # Create the tree with all the sub-packages:
            tree = otree.createOrphanTree()

            for subpackage in dialog.subpackages():
                entry = base.find(subpackage)

                # Should never happens since we fetch the subpackage for the archive:
                if not entry or not isinstance(entry, mobase.IFileTree):
                    print(
                        f"SubPackage {subpackage} not found in the archive.",
                        file=sys.stderr,
                    )
                    continue

                tree.merge(entry)

            # Move all non-selected plugins to "optional":
            optionals: List[mobase.FileTreeEntry] = []
            for entry in tree:
                if entry.isFile() and (
                    entry.hasSuffix(["esl", "esp", "esm"])
                    and entry.name() not in dialog.plugins()
                ):
                    optionals.append(entry)

            # Do not keep empty optional folder:
            if optionals:
                optional = tree.addDirectory("optional")
                for entry in optionals:
                    optional.insert(entry)

            # Handle renames:
            for original, new in dialog.renames().items():
                # Entry should be at the root:
                entry = tree.find(original)

                if not entry:
                    print(f"Plugin {original} not found, cannot rename.")
                    continue

                tree.move(entry, new)

            # Return the tree:
            return tree

        # If user requested a manual installation, we update the name (to keep it
        # in the manual installation dialog) and just notify the installation manager:
        elif dialog.isManualRequested():
            name.update(dialog.name(), mobase.GuessQuality.USER)
            return mobase.InstallResult.MANUAL_REQUESTED

        # If user canceled, we simply notify the installation manager:
        else:
            return mobase.InstallResult.CANCELED

    def _tr(self, str):
        # We need this to translate string in Python. Check the common documentation
        # for more details:
        return QApplication.translate("WizardInstaller", str)
