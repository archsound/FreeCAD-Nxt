"""Direct edits as document objects, so each stays in the model's history.

Every edit is a Part::FeaturePython that reads the faces of a base object
and holds the edited solid. The base can be anything with a solid Shape:
a Part primitive, an imported STEP solid, a Part Design Body. The base is
hidden and nests under the edit in the tree, like a boolean's operands.

An edit of a Body stands outside the Body: Part Design features cannot
follow it. Editing inside a Body is a later step.
"""

from __future__ import annotations

from typing import Any

import FreeCAD as App

from . import ops

PUSH_PULL = "PushPull"
OFFSET_FACE = "OffsetFace"
DELETE_FACE = "DeleteFace"

_LABELS = {PUSH_PULL: "PushPull", OFFSET_FACE: "OffsetFace",
           DELETE_FACE: "DeleteFace"}


def _faces(obj: Any) -> tuple[Any, list[Any]]:
    """The base's shape and the faces `obj.Faces` names on it."""
    base, names = obj.Faces
    shape = base.Shape
    faces = [shape.getElement(name) for name in names
             if name.startswith("Face")]
    if not faces:
        raise ops.DirectEditError("No face to edit")
    return shape, faces


class DirectEdit:
    """Proxy of an edit; `Kind` picks the operation."""

    def __init__(self, obj: Any, kind: str) -> None:
        obj.addProperty("App::PropertyLinkSub", "Faces", "Direct edit",
                        "The faces the edit acts on")
        obj.addProperty("App::PropertyString", "Kind", "Direct edit",
                        "Which edit this is")
        obj.setEditorMode("Kind", 1)
        obj.Kind = kind
        if kind != DELETE_FACE:
            obj.addProperty(
                "App::PropertyDistance", "Distance", "Direct edit",
                "How far the face moves along its normal; negative moves "
                "it into the solid")
        obj.Proxy = self

    def execute(self, obj: Any) -> None:
        shape, faces = _faces(obj)
        if obj.Kind == PUSH_PULL:
            result = ops.push_pull(shape, faces[0], obj.Distance.Value)
        elif obj.Kind == OFFSET_FACE:
            result = ops.offset_round(shape, faces[0], obj.Distance.Value)
        else:
            result = ops.delete_faces(shape, faces)
        obj.Shape = result

    def dumps(self) -> None:
        return None

    def loads(self, _state: Any) -> None:
        return None


class DirectEditView:
    """View proxy: the base nests under the edit and returns on delete."""

    def __init__(self, view: Any) -> None:
        view.Proxy = self

    def attach(self, view: Any) -> None:
        self.obj = view.Object

    def claimChildren(self) -> list[Any]:  # noqa: N802 - FreeCAD API
        base = self.obj.Faces[0] if self.obj.Faces else None
        return [base] if base is not None else []

    def onDelete(self, view: Any, _subs: Any) -> bool:  # noqa: N802
        base = view.Object.Faces[0] if view.Object.Faces else None
        if base is not None and base.ViewObject is not None:
            base.ViewObject.Visibility = True
        return True

    def dumps(self) -> None:
        return None

    def loads(self, _state: Any) -> None:
        return None


def make(doc: Any, kind: str, base: Any, faces: list[str],
         distance: float = 0.0) -> Any:
    """Add an edit of `kind` on `faces` of `base`, and compute it.

    Raises DirectEditError, leaving nothing behind, when the edit cannot
    be made.
    """
    obj = doc.addObject("Part::FeaturePython", _LABELS[kind])
    DirectEdit(obj, kind)
    obj.Faces = (base, faces)
    if kind != DELETE_FACE:
        obj.Distance = distance
    try:
        obj.Proxy.execute(obj)
    except ops.DirectEditError:
        doc.removeObject(obj.Name)
        raise
    if App.GuiUp and obj.ViewObject is not None:
        DirectEditView(obj.ViewObject)
        if base.ViewObject is not None:
            for name in ("ShapeAppearance", "LineColor", "PointColor"):
                if hasattr(base.ViewObject, name):
                    setattr(obj.ViewObject, name,
                            getattr(base.ViewObject, name))
            base.ViewObject.Visibility = False
    obj.purgeTouched()
    return obj
