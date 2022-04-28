# -*- encoding: utf-8 -*-

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from antlr4 import ParserRuleContext
from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QKeySequence, QPixmap, QResizeEvent, QShortcut
from PyQt6.QtWidgets import QApplication
from wizard.contexts import (
    WizardInterpreterContext,
    WizardRequireVersionsContext,
    WizardSelectContext,
    WizardSelectManyContext,
    WizardSelectOneContext,
    WizardTerminationContext,
    WizardTopLevelContext,
)
from wizard.errors import WizardError
from wizard.interpreter import WizardInterpreter
from wizard.manager import SelectOption
from wizard.runner import WizardRunnerKeywordVisitor, WizardRunnerState
from wizard.tweaks import WizardINISetting
from wizard.value import Plugin

import mobase

from .ui.wizardinstallercomplete import Ui_WizardInstallerComplete
from .ui.wizardinstallerdialog import Ui_WizardInstallerDialog
from .ui.wizardinstallererror import Ui_WizardInstallerError
from .ui.wizardinstallerpage import Ui_WizardInstallerPage
from .ui.wizardinstallerrequires import Ui_WizardInstallerRequires
from .utils import make_ini_tweaks

WizardRunnerContext = WizardInterpreterContext[WizardRunnerState, Any]


def check_version(
    context: WizardRequireVersionsContext, organizer: mobase.IOrganizer
) -> Tuple[bool, bool, bool, bool]:
    """
    Check if the requirements are ok.

    Args:
        context: The requires version context to check.
        organizer: The organizer to fetch actual versions from.

    Returns:
        A 4-tuple of boolean values, where each value is True if the installed
        version is ok, False otherwise. In order, checks are game, script extender
        graphics extender (True if there is no requirements, False otherwise since
        we cannot check in MO2), and wrye bash (always True).
    """
    game = organizer.managedGame()

    game_ok = True
    if context.game_version:
        game_ok = mobase.VersionInfo(context.game_version) <= game.version()

    # Script extender:
    se_ok = True
    if context.script_extender_version:
        se = game.feature(mobase.ScriptExtender)  # type: ignore
        if not se or not se.isInstalled():
            se_ok = False
        else:
            if mobase.VersionInfo(
                context.script_extender_version
            ) <= mobase.VersionInfo(se.getExtenderVersion()):
                se_ok = True
            else:
                se_ok = False

    # Cannot check these so...
    ge_ok = not context.graphics_extender_version

    return (game_ok, se_ok, ge_ok, True)


class WizardInstallerRequiresVersionPage(QtWidgets.QWidget):

    context: WizardRequireVersionsContext

    def __init__(
        self,
        context: WizardRequireVersionsContext,
        organizer: mobase.IOrganizer,
        parent: QtWidgets.QWidget,
    ):
        super().__init__(parent)

        self.context = context

        # Set the ui file:
        self.ui = Ui_WizardInstallerRequires()
        self.ui.setupUi(self)

        self.ui.groupBox.setStyleSheet(
            'QLabel[headercell="true"] { font-weight: bold; }'
        )

        game = organizer.managedGame()

        okIcon = QPixmap(":/MO/gui/checked-checkbox").scaled(
            16,
            16,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        noIcon = QPixmap(":/MO/gui/unchecked-checkbox").scaled(
            16,
            16,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        koIcon = QPixmap(":/MO/gui/indeterminate-checkbox").scaled(
            16,
            16,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        self.ui.labelGame.setText(game.gameName())

        # Set the required version:
        self.ui.labelGameNeed.setText(context.game_version)
        self.ui.labelScriptExtenderNeed.setText(context.script_extender_version)
        self.ui.labelGraphicsExtenderNeed.setText(context.graphics_extender_version)
        self.ui.labelWryeBashNeed.setText(context.wrye_bash_version)

        # Set the current version:
        self.ui.labelGameHave.setText(game.version().canonicalString())
        se = game.feature(mobase.ScriptExtender)  # type: ignore
        if se or se.isInstalled():
            self.ui.labelScriptExtenderHave.setText(se.getExtenderVersion())

        # Cannot check these so...
        game_ok, se_ok, ge_ok, _ = check_version(context, organizer)
        self.ui.labelGameIcon.setPixmap(okIcon if game_ok else koIcon)
        self.ui.labelScriptExtenderIcon.setPixmap(okIcon if se_ok else koIcon)
        self.ui.labelGraphicsExtenderIcon.setPixmap(noIcon)
        self.ui.labelWryeBashIcon.setPixmap(noIcon)


class WizardInstallerSelectPage(QtWidgets.QWidget):

    # Signal emitted when an item is double-clicked, only for SelectOne
    # context:
    itemDoubleClicked = pyqtSignal()

    _context: WizardSelectContext
    _images: Mapping[Path, Path]
    _currentImage: QPixmap

    def __init__(
        self,
        context: WizardSelectContext,
        images: Mapping[Path, Path],
        options: Optional[List[str]],
        parent: QtWidgets.QWidget,
    ):
        """
        Args:
            context: The context for this page.
            images: A mapping from path (in the archive) to extracted path.
            options: Potential list of options to select. Might not exactly match.
            parent: The parent widget.
        """
        super().__init__(parent)

        self._images = images

        # Set the ui file:
        self.ui = Ui_WizardInstallerPage()
        self.ui.setupUi(self)

        self.ui.optionList.currentItemChanged.connect(self.onCurrentItemChanged)

        # Create list item widgets:
        for option in context.options:
            item = QtWidgets.QListWidgetItem()
            self.ui.optionList.addItem(item)

        self.update_context(context)

        # Extract previous select options:
        previous_options = []
        if options:
            previous_options = [
                option for option in context.options if option.name in options
            ]
        else:
            if isinstance(context, WizardSelectManyContext):
                previous_options = context.defaults
            elif isinstance(context, WizardSelectOneContext):
                previous_options = [context.default]

        # Set the default values:
        for i, option in enumerate(context.options):
            item = self.ui.optionList.item(i)
            if isinstance(context, WizardSelectManyContext):
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                if option in previous_options:
                    item.setCheckState(Qt.CheckState.Checked)
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
            elif (
                isinstance(context, WizardSelectOneContext)
                and option in previous_options
            ):
                item.setSelected(True)
                self.ui.optionList.setCurrentItem(item)

        if isinstance(context, WizardSelectOneContext):
            self.ui.optionList.doubleClicked.connect(self.itemDoubleClicked.emit)

    def update_context(self, context: WizardSelectContext):

        self._context = context

        options = self._context.options
        assert len(options) == self.ui.optionList.count()

        self.ui.selectDescriptionLabel.setText(context.description)
        self.ui.selectDescriptionLabel.setMargin(4)

        # Update the content of the items:
        for i, option in enumerate(options):
            item = self.ui.optionList.item(i)
            item.setText(option.name)
            item.setData(Qt.ItemDataRole.UserRole, option)

        # No item selected, select the first one:
        if not self.ui.optionList.currentItem():
            self.ui.optionList.setCurrentRow(0)

    def onCurrentItemChanged(
        self, current: QtWidgets.QListWidgetItem, previous: QtWidgets.QListWidgetItem
    ):
        option: SelectOption = current.data(Qt.ItemDataRole.UserRole)
        self.ui.descriptionTextEdit.setText(option.description)
        image = option.image
        if image and Path(image) in self._images:
            target = self._images[Path(image)]
            self._currentImage = QPixmap(target.as_posix())
        else:
            self._currentImage = QPixmap()

        self.ui.imageLabel.setPixmap(self.getResizedImage())

    def getResizedImage(self) -> QPixmap:
        if self._currentImage.isNull():
            return self._currentImage
        return self._currentImage.scaled(
            self.ui.imageLabel.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.ui.imageLabel.setPixmap(self.getResizedImage())

    def selectedOptions(self) -> List[SelectOption]:
        options = []
        if isinstance(self._context, WizardSelectOneContext):
            options.append(
                self.ui.optionList.currentItem().data(Qt.ItemDataRole.UserRole)
            )
        else:
            for i in range(self.ui.optionList.count()):
                item = self.ui.optionList.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    options.append(item.data(Qt.ItemDataRole.UserRole))
        return options

    def selected(self) -> WizardSelectContext:
        if isinstance(self._context, WizardSelectOneContext):
            return self._context.select(self.selectedOptions()[0])
        elif isinstance(self._context, WizardSelectManyContext):
            return self._context.select(self.selectedOptions())
        else:
            return self._context  # type: ignore


class WizardInstallerCompletePage(QtWidgets.QWidget):
    def __init__(
        self,
        context: WizardTerminationContext[WizardRunnerState],
        parent: QtWidgets.QWidget,
    ):
        super().__init__(parent)

        # Set the ui file:
        self.ui = Ui_WizardInstallerComplete()
        self.ui.setupUi(self)

        self.setStyleSheet('QLabel[heading="true"] { font-weight: bold; }')

        self.context = context
        self.state = context.state

        # Retrieve the keyword visitor:
        kvisitor: WizardRunnerKeywordVisitor = context.factory.kvisitor  # type: ignore

        # The list of plugins in selected sub-packages:
        plugins: Set[Plugin] = set()

        # SubPackages:
        for sp in kvisitor.subpackages:
            item = QtWidgets.QListWidgetItem()
            item.setText(sp.name)
            if sp.name in self.state.subpackages:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            plugins.update(kvisitor.plugins_for(sp))
            self.ui.subpackagesList.addItem(item)

        # Switch the renamed plugins:
        for plugin in list(plugins):
            if plugin in self.state.renames:
                plugins.remove(plugin)
                plugins.add(Plugin(self.state.renames[plugin]))

        # Plugins:
        for plugin in sorted(plugins):
            item = QtWidgets.QListWidgetItem()
            item.setText(plugin.name)
            if plugin in self.state.plugins:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.ui.pluginsList.addItem(item)

        # INI Tweaks:
        self.ui.tweaksWidget.setVisible(bool(self.state.tweaks))
        self.ui.tweaksList.currentItemChanged.connect(self.onCurrentTweakItemChanged)
        if self.state.tweaks:
            # Group the tweaks per file:
            tweaks = {
                file: self.state.tweaks.tweaks(file)
                for file in self.state.tweaks.files()
            }

            for file, ftweaks in tweaks.items():
                item = QtWidgets.QListWidgetItem()
                item.setText(file.replace("\\", "/"))
                item.setData(Qt.ItemDataRole.UserRole, ftweaks)
                self.ui.tweaksList.addItem(item)

            self.ui.tweaksTextEdit.setFont(
                QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            )
            self.ui.tweaksList.setCurrentRow(0)

        # Notes:
        md = ""
        for note in self.state.notes:
            md += f"- {note}\n"
        self.ui.notesTextEdit.document().setIndentWidth(10)
        self.ui.notesTextEdit.setMarkdown(md)

    def onCurrentTweakItemChanged(
        self, current: QtWidgets.QListWidgetItem, previous: QtWidgets.QListWidgetItem
    ):
        # Clear text area and create the tweaks:
        self.ui.tweaksTextEdit.clear()
        self.ui.tweaksTextEdit.appendPlainText(
            make_ini_tweaks(current.data(Qt.ItemDataRole.UserRole))
        )

    def subpackages(self) -> List[str]:
        """
        Returns:
            The list of subpackages selected in the UI (either automatically by the
            interpreter or by the user).
        """
        sp: List[str] = []
        for i in range(self.ui.subpackagesList.count()):
            item = self.ui.subpackagesList.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                sp.append(item.text())
        return sp

    def plugins(self) -> Dict[str, bool]:
        """
        Returns:
            The list of plugins selected in the UI (either automatically by the
            interpreter or by the user).
        """
        sp: Dict[str, bool] = {}
        for i in range(self.ui.pluginsList.count()):
            item = self.ui.pluginsList.item(i)
            sp[item.text()] = item.checkState() == Qt.CheckState.Checked
        return sp

    def tweaks(self) -> Mapping[str, List[WizardINISetting]]:
        """
        Returns:
            The list of tweaks created by the wizard. The returned value maps filenames
            to INI tweaks.
        """
        rets = {}
        for i in range(self.ui.tweaksList.count()):
            item = self.ui.tweaksList.item(i)
            rets[item.text()] = item.data(Qt.ItemDataRole.UserRole)
        return rets


class WizardInstallerCancelPage(QtWidgets.QWidget):
    def __init__(
        self,
        context: WizardTerminationContext[WizardRunnerState],
        parent: QtWidgets.QWidget,
    ):
        super().__init__(parent)

        # Set the ui file (same UI file for both cancel and error):
        self.ui = Ui_WizardInstallerError()
        self.ui.setupUi(self)

        self.ui.titleLabel.setText(
            "The installation was cancelled by the installer with the following reason."
        )
        self.ui.iconLabel.setPixmap(
            self.style()
            .standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning)
            .pixmap(24, 24)
        )
        self.ui.messageEdit.setText(context.message())


class WizardInstallerErrorPage(QtWidgets.QWidget):
    def __init__(
        self,
        error: WizardError,
        parent: QtWidgets.QWidget,
    ):
        super().__init__(parent)

        # Set the ui file (same UI file for both cancel and error):
        self.ui = Ui_WizardInstallerError()
        self.ui.setupUi(self)

        self.ui.titleLabel.setText(
            "An error occurred during the installation of the script, "
            "this is probably due to an incorrect script file (wizard.txt) in the "
            "archive."
        )
        self.ui.iconLabel.setPixmap(
            self.style()
            .standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxCritical)
            .pixmap(24, 24)
        )
        self.ui.messageEdit.setText(str(error))


class WizardInstallerDialog(QtWidgets.QDialog):

    # Flag to indicate if the user chose to do a manual installation:
    _manual: bool = False

    # The organizer:
    _organizer: mobase.IOrganizer

    # The interpreter:
    _interpreter: WizardInterpreter
    _images: Mapping[Path, Path]
    _options: Mapping[str, List[str]]

    # The Wizard MO2 interface:
    _start_context: WizardTopLevelContext

    # Mapping from context to selected options:
    _pages: Mapping[ParserRuleContext, WizardInstallerSelectPage]

    def __init__(
        self,
        organizer: mobase.IOrganizer,
        interpreter: WizardInterpreter,
        context: WizardTopLevelContext[WizardRunnerState],
        name: mobase.GuessedString,
        images: Mapping[Path, Path],
        options: Mapping[str, List[str]],
        parent: QtWidgets.QWidget,
    ):
        """
        Args:
            interpreter: The interpreter to use.
            context: The initial context of the script.
            name: The name of the mod.
            images: A mapping from path (in the archive) to extracted path.
            options: The previously selected options.
            parent: The parent widget.
        """
        super().__init__(parent)

        self._organizer = organizer
        self._interpreter = interpreter
        self._images = images
        self._options = options
        self._start_context = context
        self._pages = {}

        # Set the ui file:
        self.ui = Ui_WizardInstallerDialog()
        self.ui.setupUi(self)

        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)

        # mobase.GuessedString contains multiple names with various level of
        # "guess". Using .variants() returns the list of names, and doing str(name)
        # will return the most-likely value.
        for value in name.variants():
            self.ui.nameCombo.addItem(value)
        self.ui.nameCombo.completer().setCaseSensitivity(
            Qt.CaseSensitivity.CaseSensitive
        )
        self.ui.nameCombo.setCurrentIndex(self.ui.nameCombo.findText(str(name)))

        # We need to connect the Cancel / Manual buttons. We can of course use
        # PyQt6 signal/slot syntax:
        self.ui.cancelBtn.clicked.connect(self.reject)

        def manualClicked():
            self._manual = True
            self.reject()

        self.ui.manualBtn.clicked.connect(manualClicked)

        self.ui.prevBtn.clicked.connect(self.previousClicked)
        self.ui.nextBtn.clicked.connect(self.nextClicked)

        backShortcut = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self)
        backShortcut.activated.connect(self.previousClicked)  # type: ignore

    @property
    def scriptButtonClicked(self) -> pyqtSignal:
        return self.ui.scriptBtn.clicked  # type: ignore

    def name(self):
        return self.ui.nameCombo.currentText()

    def subpackages(self):
        """
        Returns:
            The list of subpackages to install. Only valid if exec() returned
            Accepted.
        """
        # Note: We cannot fetch it from the state since the user can modify it in the
        # UI.
        widget = self.ui.stackedWidget.currentWidget()
        assert isinstance(widget, WizardInstallerCompletePage)
        return widget.subpackages()

    def plugins(self) -> Dict[str, bool]:
        """
        Returns:
            The list of plugins to install and enable. Only valid if exec() returned
            Accepted.
        """
        # Note: We cannot fetch it from the state since the user can modify it in the
        # UI.
        widget = self.ui.stackedWidget.currentWidget()
        assert isinstance(widget, WizardInstallerCompletePage)
        return widget.plugins()

    def renames(self) -> Mapping[str, str]:
        """
        Returns:
            The mapping of renames for plugins. Only valid if exec() returned Accepted.
        """
        widget = self.ui.stackedWidget.currentWidget()
        assert isinstance(widget, WizardInstallerCompletePage)
        return {
            plugin.name: new_name for plugin, new_name in widget.state.renames.items()
        }

    def tweaks(self) -> Mapping[str, List[WizardINISetting]]:
        """
        Returns:
            The list of tweaks per file. Only valid if exec() returned Accepted.
        """
        widget = self.ui.stackedWidget.currentWidget()
        assert isinstance(widget, WizardInstallerCompletePage)
        return widget.tweaks()

    def selectedOptions(self) -> Mapping[str, List[str]]:
        """
        Returns:
            The list of all currently selected options.
        """
        result = {}
        for i in range(self.ui.stackedWidget.count()):
            page = self.ui.stackedWidget.widget(i)
            if isinstance(page, WizardInstallerSelectPage):
                result[page._context.description] = [
                    option.name for option in page.selectedOptions()
                ]
        return result

    def isManualRequested(self):
        return self._manual

    def previousClicked(self):
        index = self.ui.stackedWidget.currentIndex()
        if index > 0:
            self.ui.stackedWidget.removeWidget(self.ui.stackedWidget.widget(index))

        self._update_prev_button()
        self._update_next_button()
        self._update_focus()

    def nextClicked(self):
        widget = self.ui.stackedWidget.currentWidget()

        try:
            if isinstance(widget, WizardInstallerSelectPage):
                context = widget.selected().exec()
            elif isinstance(widget, WizardInstallerRequiresVersionPage):
                context = widget.context.exec()
            else:
                self.accept()
                return

            context = self._exec_until(context)

            if context.context in self._pages:
                page = self._pages[context.context]
                page.update_context(context)
            else:
                page = self._make_page(context)

        except WizardError as ex:
            page = WizardInstallerErrorPage(ex, self)

        index = self.ui.stackedWidget.addWidget(page)
        self.ui.stackedWidget.setCurrentIndex(index)
        self._update_prev_button()
        self._update_next_button()
        self._update_focus()

    def _update_focus(self):
        widget = self.ui.stackedWidget.currentWidget()
        if isinstance(widget, WizardInstallerSelectPage):
            widget.ui.optionList.setFocus()

    def _update_prev_button(self):
        self.ui.prevBtn.setDisabled(self.ui.stackedWidget.currentIndex() <= 0)

    def _update_next_button(self):
        widget = self.ui.stackedWidget.currentWidget()

        self.ui.nextBtn.setDisabled(False)

        name: str = self.ui.nextBtn.text()
        if isinstance(widget, WizardInstallerSelectPage):
            name = self.tr("Next")
        elif isinstance(widget, WizardInstallerRequiresVersionPage):
            name = self.tr("Install anyway")
        elif isinstance(widget, (WizardInstallerCancelPage, WizardInstallerErrorPage)):
            self.ui.nextBtn.setDisabled(True)
        else:
            name = self.tr("Install")

        self.ui.nextBtn.setText(name)

    def _exec_until(self, context: WizardRunnerContext) -> WizardRunnerContext:
        context = self._interpreter.exec_until(
            context,
            (
                WizardSelectContext,
                WizardRequireVersionsContext,
            ),
        )

        # If all requirements are ok, skip the context:
        if isinstance(context, WizardRequireVersionsContext):
            if all(check_version(context, self._organizer)):
                return self._exec_until(context.exec())

        return context

    def _make_page(self, context: WizardRunnerContext) -> QtWidgets.QWidget:
        page: QtWidgets.QWidget
        if isinstance(context, WizardSelectContext):
            page = WizardInstallerSelectPage(
                context,
                self._images,
                self._options.get(context.description, None),
                self,
            )
            page.itemDoubleClicked.connect(self.nextClicked)
            self._pages[context.context] = page  # type: ignore
        elif isinstance(context, WizardRequireVersionsContext):
            page = WizardInstallerRequiresVersionPage(context, self._organizer, self)
        elif isinstance(context, WizardTerminationContext):
            if context.is_cancel():
                page = WizardInstallerCancelPage(context, self)
            else:
                page = WizardInstallerCompletePage(context, self)

        return page

    def exec(self):
        try:
            context = self._exec_until(self._start_context)
            page = self._make_page(context)
        except WizardError as ex:
            page = WizardInstallerErrorPage(ex, self)
        self.ui.stackedWidget.addWidget(page)
        self._update_prev_button()
        self._update_next_button()
        self._update_focus()
        return super().exec()

    def tr(self, str):
        return QApplication.translate("WizardInstallerDialog", str)
