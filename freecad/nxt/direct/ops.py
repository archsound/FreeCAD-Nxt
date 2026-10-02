"""Direct edits on a solid: move a face, resize a round face, remove faces.

Shape in, shape out: nothing here knows about documents, features or the
GUI, so it runs under FreeCADCmd and is tested there
(tests/test_direct_ops.py). features.py wraps each edit in a document
object so it stays in the model's history.

Distances are along the face's outward normal, the way the face moves:
positive adds material on a flat face, and on a round face makes a hole
smaller and a boss larger.

What the kernel does not give us: OpenCascade has no "move this face and
stretch its neighbours" operation, so a flat face moves by adding or
removing the prism it sweeps, and a round face by rebuilding its
cylinder. Faces that lean against the moved one are cut or extended
straight, not re-solved.
"""

from __future__ import annotations

import math
from typing import Any

import Part

#: Lengths below this are no edit at all (mm).
TOLERANCE = 1e-7


class DirectEditError(ValueError):
    """The edit cannot be made on this face; the message says why."""


def _checked(result: Any, what: str) -> Any:
    """`result` if it is a usable solid, else a DirectEditError."""
    if result.isNull() or not result.isValid() or not result.Solids:
        raise DirectEditError(f"{what} did not leave a valid solid")
    return result


def _middle(face: Any) -> tuple[float, float]:
    """The middle of the face's parameter range."""
    u0, u1, v0, v1 = face.ParameterRange
    return (u0 + u1) / 2.0, (v0 + v1) / 2.0


def is_flat(face: Any) -> bool:
    """Whether the face lies on a plane."""
    return bool(face.Surface.TypeId == "Part::GeomPlane")


def is_round(face: Any) -> bool:
    """Whether the face is a whole cylinder: a hole's wall, or a boss's."""
    if face.Surface.TypeId != "Part::GeomCylinder":
        return False
    u0, u1, _v0, _v1 = face.ParameterRange
    return abs((u1 - u0) - 2.0 * math.pi) < 1e-6


def is_hole(face: Any) -> bool:
    """Whether a round face is a hole's wall: its normal points at the axis."""
    u, v = _middle(face)
    point = face.valueAt(u, v)
    surface = face.Surface
    along = (point - surface.Center).dot(surface.Axis)
    outward = point - (surface.Center + surface.Axis * along)
    return bool(face.normalAt(u, v).dot(outward) < 0.0)


def push_pull(shape: Any, face: Any, distance: float) -> Any:
    """`shape` with a flat `face` moved `distance` along its normal.

    Positive pulls the face out, adding the prism it sweeps; negative
    pushes it in, removing it.
    """
    if not is_flat(face):
        raise DirectEditError("Push/pull needs a flat face")
    if abs(distance) < TOLERANCE:
        return shape
    prism = face.extrude(face.normalAt(*_middle(face)) * distance)
    moved = shape.fuse(prism) if distance > 0 else shape.cut(prism)
    return _checked(moved.removeSplitter(), "Push/pull")


def offset_round(shape: Any, face: Any, distance: float) -> Any:
    """`shape` with a round `face` moved `distance` along its normal.

    The radius of a boss grows with a positive distance; the radius of a
    hole shrinks, since the wall of a hole faces its axis.
    """
    if not is_round(face):
        raise DirectEditError("Offset needs a whole cylindrical face")
    if abs(distance) < TOLERANCE:
        return shape
    surface = face.Surface
    hole = is_hole(face)
    old = surface.Radius
    new = old - distance if hole else old + distance
    if new < TOLERANCE:
        raise DirectEditError("The offset leaves no radius")
    _u0, _u1, v0, v1 = face.ParameterRange
    start = surface.Center + surface.Axis * v0

    def cylinder(radius: float) -> Any:
        return Part.makeCylinder(radius, v1 - v0, start, surface.Axis)

    if hole and new > old:
        result = shape.cut(cylinder(new))
    elif hole:
        result = delete_faces(shape, [face]).cut(cylinder(new))
    elif new > old:
        result = shape.fuse(cylinder(new))
    else:
        result = shape.cut(cylinder(old).cut(cylinder(new)))
    return _checked(result.removeSplitter(), "Offset")


def delete_faces(shape: Any, faces: list[Any]) -> Any:
    """`shape` with `faces` removed and the gap closed by their neighbours.

    Removes a hole, a fillet, a chamfer, a boss or a pocket when every
    face of it is given.
    """
    if not faces:
        return shape
    try:
        healed = shape.defeaturing(faces)
    except Exception as error:
        raise DirectEditError(
            "The neighbouring faces cannot close the gap") from error
    _checked(healed, "Delete face")
    if len(healed.Faces) >= len(shape.Faces):
        raise DirectEditError("The neighbouring faces cannot close the gap")
    return healed
