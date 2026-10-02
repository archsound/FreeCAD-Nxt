"""The addon's GUI commands.

Plain duck-typed command classes, registered by `init_gui`. Imports of the
modules that do the work are deferred to `Activated`, so registering the
commands at startup costs nothing and pulls in no QtQuick.
"""

from __future__ import annotations

from typing import Any

import FreeCADGui as Gui

from .i18n import QT_TRANSLATE_NOOP

ICON = "FreeCAD-Nxt.svg"


class _Command:
    """Shared plumbing: resources from class attributes."""

    menu_text: str = ""
    tool_tip: str = ""
    pixmap: str = ""

    def GetResources(self) -> dict[str, str]:  # noqa: N802 - FreeCAD command API
        resources = {"MenuText": self.menu_text, "ToolTip": self.tool_tip}
        if self.pixmap:
            resources["Pixmap"] = self.pixmap
        return resources

    def IsActive(self) -> bool:  # noqa: N802 - FreeCAD command API
        return True


class ModelPanel(_Command):
    """Show or hide the Nxt model panel."""

    menu_text = QT_TRANSLATE_NOOP("Nxt_ModelPanel", "Nxt model panel")
    tool_tip = QT_TRANSLATE_NOOP(
        "Nxt_ModelPanel",
        "Model history as a timeline, with a draggable rollback bar")
    pixmap = ICON

    def Activated(self) -> None:  # noqa: N802 - FreeCAD command API
        from .tree import panel
        panel.toggle()


class ModelPanelOverlay(_Command):
    """Draw the panel as floating labels over the 3D view."""

    menu_text = QT_TRANSLATE_NOOP("Nxt_ModelPanelOverlay",
                                  "Nxt panel overlay")
    tool_tip = QT_TRANSLATE_NOOP(
        "Nxt_ModelPanelOverlay",
        "Draw the model panel as floating labels with no background")

    def Activated(self) -> None:  # noqa: N802 - FreeCAD command API
        from .tree import panel
        panel.toggle_overlay()

    def IsActive(self) -> bool:  # noqa: N802 - FreeCAD command API
        from .tree import panel
        return panel.is_open()


class PropertyInspector(_Command):
    """Open FreeCAD's Property editor in an inspector beside the panel."""

    menu_text = QT_TRANSLATE_NOOP("Nxt_PropertyInspector",
                                  "Nxt Property Inspector")
    tool_tip = QT_TRANSLATE_NOOP(
        "Nxt_PropertyInspector",
        "Show the selection's properties beside the model panel")

    def Activated(self) -> None:  # noqa: N802 - FreeCAD command API
        from . import property_inspector
        property_inspector.toggle()


class Isolate(_Command):
    """Show only the selection in the 3D view, until told otherwise."""

    menu_text = QT_TRANSLATE_NOOP("Nxt_Isolate", "Isolate")
    tool_tip = QT_TRANSLATE_NOOP(
        "Nxt_Isolate",
        "Show only the selected objects in the 3D view; again to exit")
    pixmap = "Std_ShowSelection"

    def Activated(self) -> None:  # noqa: N802 - FreeCAD command API
        from . import services
        isolation = services.isolation()
        if isolation is not None:
            isolation.toggle_selection()

    def IsActive(self) -> bool:  # noqa: N802 - FreeCAD command API
        from . import services
        isolation = services.isolation()
        if isolation is None:
            return False
        return isolation.active() or bool(Gui.Selection.getSelection())


class Reload(_Command):
    """Hot-reload the addon's Python modules during development."""

    menu_text = QT_TRANSLATE_NOOP("Nxt_Reload", "Reload Nxt")
    tool_tip = QT_TRANSLATE_NOOP("Nxt_Reload",
                                 "Hot-reload the addon's Python modules")

    def Activated(self) -> None:  # noqa: N802 - FreeCAD command API
        from . import reload_all
        reload_all()


class _DirectEdit(_Command):
    """Shared by the direct edits: act on the faces selected on one object."""

    kind: str = ""
    #: What to tell the user when the face is the wrong sort.
    needs: str = ""
    #: Which faces the edit takes: "flat", "round", or "" for any number.
    wants: str = ""

    @staticmethod
    def _picked() -> tuple[Any, list[str]] | None:
        """(base object, face names) of the selection, or None."""
        try:
            selection = Gui.Selection.getSelectionEx()
        except Exception:
            return None
        if len(selection) != 1:
            return None
        obj = selection[0].Object
        faces = [name for name in selection[0].SubElementNames
                 if name.startswith("Face")]
        if not faces or not hasattr(obj, "Shape"):
            return None
        # A face picked on a Body arrives as its tip feature's; the edit
        # stands on the Body, so the Body is what gets hidden.
        for parent in obj.InList:
            if (parent.isDerivedFrom("PartDesign::Body")
                    and parent.Tip == obj):
                return parent, faces
        return obj, faces

    def IsActive(self) -> bool:  # noqa: N802 - FreeCAD command API
        picked = self._picked()
        if picked is None:
            return False
        return not self.wants or len(picked[1]) == 1

    def Activated(self) -> None:  # noqa: N802 - FreeCAD command API
        from .direct import features, ops
        from .qt import QtWidgets
        picked = self._picked()
        if picked is None:
            return
        base, faces = picked
        distance = 0.0
        window = Gui.getMainWindow()
        if self.wants:
            face = base.Shape.getElement(faces[0])
            fits = (ops.is_flat(face) if self.wants == "flat"
                    else ops.is_round(face))
            if not fits:
                QtWidgets.QMessageBox.information(
                    window, self.menu_text, self.needs)
                return
            distance, ok = QtWidgets.QInputDialog.getDouble(
                window, self.menu_text, "Distance (mm)", 1.0,
                -1e6, 1e6, 3)
            if not ok:
                return
        doc = base.Document
        doc.openTransaction(self.menu_text)
        try:
            edit = features.make(doc, self.kind, base, faces, distance)
        except ops.DirectEditError as error:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(window, self.menu_text, str(error))
            return
        doc.commitTransaction()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, edit.Name)


class PushPull(_DirectEdit):
    """Move a flat face along its normal, adding or removing material."""

    kind = "PushPull"
    wants = "flat"
    menu_text = QT_TRANSLATE_NOOP("Nxt_PushPull", "Push/pull face")
    tool_tip = QT_TRANSLATE_NOOP(
        "Nxt_PushPull",
        "Move the selected flat face along its normal; a negative "
        "distance pushes it into the solid")
    needs = QT_TRANSLATE_NOOP("Nxt_PushPull", "Select one flat face.")


class OffsetFace(_DirectEdit):
    """Change the radius of a hole or a round boss."""

    kind = "OffsetFace"
    wants = "round"
    menu_text = QT_TRANSLATE_NOOP("Nxt_OffsetFace", "Offset round face")
    tool_tip = QT_TRANSLATE_NOOP(
        "Nxt_OffsetFace",
        "Move the selected cylindrical face along its normal: a hole "
        "gets smaller, a boss larger; negative does the opposite")
    needs = QT_TRANSLATE_NOOP(
        "Nxt_OffsetFace", "Select one whole cylindrical face.")


class DeleteFace(_DirectEdit):
    """Remove the selected faces and close the gap with their neighbours."""

    kind = "DeleteFace"
    menu_text = QT_TRANSLATE_NOOP("Nxt_DeleteFace", "Delete face")
    tool_tip = QT_TRANSLATE_NOOP(
        "Nxt_DeleteFace",
        "Remove the selected faces (a hole, a fillet, a boss) and close "
        "the gap with the neighbouring faces")


class MenuGroup:
    """The FreeCAD-Nxt submenu of the View menu.

    A FreeCAD command group: a command whose `GetCommands` lists others.
    With DropDownMenu set, FreeCAD draws a group placed in a menu as a
    submenu holding those commands, which is how the addon's entries are
    kept together rather than scattered along the View menu.
    """

    def GetCommands(self) -> list[str]:  # noqa: N802 - FreeCAD command API
        return list(MENU)

    def GetResources(self) -> dict[str, object]:  # noqa: N802
        return {"MenuText": "FreeCAD-Nxt",
                "ToolTip": QT_TRANSLATE_NOOP("Nxt_Menu",
                                             "The Nxt model panel's commands"),
                "Pixmap": ICON,
                "DropDownMenu": True,
                "Exclusive": False}

    def IsActive(self) -> bool:  # noqa: N802 - FreeCAD command API
        return True


COMMANDS: dict[str, type[_Command]] = {
    "Nxt_ModelPanel": ModelPanel,
    "Nxt_ModelPanelOverlay": ModelPanelOverlay,
    "Nxt_PropertyInspector": PropertyInspector,
    "Nxt_Isolate": Isolate,
    "Nxt_Reload": Reload,
    "Nxt_PushPull": PushPull,
    "Nxt_OffsetFace": OffsetFace,
    "Nxt_DeleteFace": DeleteFace,
}

#: The FreeCAD-Nxt submenu of the View menu. Reload is listed for now,
#: while the addon is being developed; it is not a feature.
MENU = ("Nxt_ModelPanel", "Nxt_ModelPanelOverlay", "Nxt_PropertyInspector",
        "Nxt_Isolate", "Nxt_PushPull", "Nxt_OffsetFace", "Nxt_DeleteFace",
        "Nxt_Reload")

#: What goes in the View menu itself: the submenu.
GROUP = "Nxt_Menu"


def register() -> None:
    for name, command in COMMANDS.items():
        Gui.addCommand(name, command())
    Gui.addCommand(GROUP, MenuGroup())
