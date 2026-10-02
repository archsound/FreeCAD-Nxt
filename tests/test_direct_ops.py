"""Direct edits: push/pull, offset a round face, delete faces.

These need FreeCAD's own Part module, so they run under FreeCADCmd and
are skipped by plain Python (as on the checks runner).

Run with: FreeCADCmd tests/test_direct_ops.py
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import FreeCAD as App
    import Part
except ImportError:
    print("skipped: needs FreeCAD (run with FreeCADCmd)")
    sys.exit(0)

# FreeCAD has its own `freecad` package; addons join it by path, which is
# what FreeCAD does for a folder in Mod.
import freecad  # noqa: E402

freecad.__path__.append(str(ROOT / "freecad"))

from freecad.nxt.direct import features, ops  # noqa: E402


def box() -> Any:
    return Part.makeBox(10, 10, 10)


def top(shape: Any) -> Any:
    return max((f for f in shape.Faces if ops.is_flat(f)),
               key=lambda f: f.CenterOfMass.z)


def rounds(shape: Any) -> list[Any]:
    return [f for f in shape.Faces if ops.is_round(f)]


def holed() -> Any:
    """The box with a through hole of radius 2 down its middle."""
    return box().cut(Part.makeCylinder(2, 10, App.Vector(5, 5, 0)))


def filleted() -> Any:
    """The box with one edge rounded to radius 1."""
    shape = box()
    return shape.makeFillet(1, shape.Edges[:1])


class PushPull(unittest.TestCase):
    def test_pull_adds_the_swept_prism(self) -> None:
        shape = box()
        pulled = ops.push_pull(shape, top(shape), 5)
        self.assertAlmostEqual(pulled.Volume, 1500, places=6)
        self.assertEqual(len(pulled.Faces), 6)

    def test_push_removes_it(self) -> None:
        shape = box()
        pushed = ops.push_pull(shape, top(shape), -3)
        self.assertAlmostEqual(pushed.Volume, 700, places=6)
        self.assertEqual(len(pushed.Faces), 6)

    def test_a_hole_follows_a_pulled_face_only_as_far_as_it_went(self) -> None:
        # The kernel does not stretch neighbours: the prism the ring-shaped
        # top sweeps carries the hole up with it.
        shape = holed()
        pulled = ops.push_pull(shape, top(shape), 5)
        self.assertAlmostEqual(
            pulled.Volume, 1500 - math.pi * 4 * 15, places=5)

    def test_zero_is_no_edit(self) -> None:
        shape = box()
        self.assertIs(ops.push_pull(shape, top(shape), 0), shape)

    def test_a_round_face_is_refused(self) -> None:
        shape = holed()
        with self.assertRaises(ops.DirectEditError):
            ops.push_pull(shape, rounds(shape)[0], 1)

    def test_pushing_through_the_solid_is_refused(self) -> None:
        shape = box()
        with self.assertRaises(ops.DirectEditError):
            ops.push_pull(shape, top(shape), -10)


class OffsetRound(unittest.TestCase):
    def test_a_hole_is_told_from_a_boss(self) -> None:
        self.assertTrue(ops.is_hole(rounds(holed())[0]))
        boss = box().fuse(Part.makeCylinder(2, 5, App.Vector(5, 5, 10)))
        self.assertFalse(ops.is_hole(rounds(boss)[0]))

    def test_a_hole_shrinks_with_a_positive_distance(self) -> None:
        shape = holed()
        smaller = ops.offset_round(shape, rounds(shape)[0], 1)
        self.assertAlmostEqual(smaller.Volume, 1000 - math.pi * 10, places=5)

    def test_a_hole_grows_with_a_negative_distance(self) -> None:
        shape = holed()
        larger = ops.offset_round(shape, rounds(shape)[0], -1)
        self.assertAlmostEqual(larger.Volume, 1000 - math.pi * 90, places=5)

    def test_a_boss_grows_and_shrinks(self) -> None:
        shape = box().fuse(Part.makeCylinder(2, 5, App.Vector(5, 5, 10)))
        wall = rounds(shape)[0]
        self.assertAlmostEqual(ops.offset_round(shape, wall, 1).Volume,
                               1000 + math.pi * 9 * 5, places=5)
        self.assertAlmostEqual(ops.offset_round(shape, wall, -1).Volume,
                               1000 + math.pi * 1 * 5, places=5)

    def test_closing_a_hole_completely_is_refused(self) -> None:
        shape = holed()
        with self.assertRaises(ops.DirectEditError):
            ops.offset_round(shape, rounds(shape)[0], 2)

    def test_a_fillet_is_not_a_whole_cylinder(self) -> None:
        shape = filleted()
        fillet = [f for f in shape.Faces
                  if f.Surface.TypeId == "Part::GeomCylinder"]
        with self.assertRaises(ops.DirectEditError):
            ops.offset_round(shape, fillet[0], 0.5)


class DeleteFaces(unittest.TestCase):
    def test_a_hole_is_filled(self) -> None:
        shape = holed()
        healed = ops.delete_faces(shape, rounds(shape))
        self.assertAlmostEqual(healed.Volume, 1000, places=5)
        self.assertEqual(len(healed.Faces), 6)

    def test_a_fillet_is_squared_off(self) -> None:
        shape = filleted()
        fillet = [f for f in shape.Faces
                  if f.Surface.TypeId == "Part::GeomCylinder"]
        self.assertAlmostEqual(ops.delete_faces(shape, fillet).Volume,
                               1000, places=5)

    def test_a_face_the_neighbours_cannot_replace_is_refused(self) -> None:
        shape = box()
        with self.assertRaises(ops.DirectEditError):
            ops.delete_faces(shape, [top(shape)])


class Features(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = App.newDocument("DirectEdit")
        self.base = self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()

    def tearDown(self) -> None:
        App.closeDocument(self.doc.Name)

    def _top_name(self) -> str:
        faces = self.base.Shape.Faces
        best = max(range(len(faces)), key=lambda i: faces[i].CenterOfMass.z)
        return f"Face{best + 1}"

    def test_an_edit_follows_its_distance_and_its_base(self) -> None:
        edit = features.make(self.doc, features.PUSH_PULL, self.base,
                             [self._top_name()], 5)
        self.assertAlmostEqual(edit.Shape.Volume, 1500, places=6)
        edit.Distance = -2
        self.doc.recompute()
        self.assertAlmostEqual(edit.Shape.Volume, 800, places=6)
        self.base.Length = 20
        self.doc.recompute()
        self.assertAlmostEqual(edit.Shape.Volume, 1600, places=6)

    def test_edits_stack(self) -> None:
        first = features.make(self.doc, features.PUSH_PULL, self.base,
                              [self._top_name()], 5)
        faces = first.Shape.Faces
        side = max(range(len(faces)), key=lambda i: faces[i].CenterOfMass.x)
        second = features.make(self.doc, features.PUSH_PULL, first,
                               [f"Face{side + 1}"], 10)
        self.assertAlmostEqual(second.Shape.Volume, 3000, places=6)

    def test_an_edit_that_fails_leaves_nothing_behind(self) -> None:
        before = len(self.doc.Objects)
        with self.assertRaises(ops.DirectEditError):
            features.make(self.doc, features.PUSH_PULL, self.base,
                          [self._top_name()], -10)
        self.assertEqual(len(self.doc.Objects), before)

    def test_an_edit_survives_save_and_reopen(self) -> None:
        import tempfile
        features.make(self.doc, features.PUSH_PULL, self.base,
                      [self._top_name()], 5)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "edit.FCStd")
            self.doc.saveAs(path)
            again = App.openDocument(path)
            try:
                edit = again.getObject("PushPull")
                edit.Distance = 1
                again.recompute()
                self.assertAlmostEqual(edit.Shape.Volume, 1100, places=6)
            finally:
                App.closeDocument(again.Name)
                self.doc = App.newDocument("DirectEdit")


suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
outcome = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if outcome.wasSuccessful() else 1)
