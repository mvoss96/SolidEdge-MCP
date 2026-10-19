"""Live checks for the fixes on fix/com-workarounds: feature targets by name, ungrounding,
circular patterns, ordered mirror copies, interference and saving onto the document's own file.
"""

import math

import pytest

pytestmark = pytest.mark.integration

PLATE = 0.2  # m, square base plate 0..0.2 in x and y, 0.01 thick
BOSS_R = 0.005
BOSS_H = 0.01
BOSS_VOLUME = math.pi * BOSS_R**2 * BOSS_H


def _volume(stack):
    return stack.query.get_volume()["volume"]


def _plate(stack):
    stack.sketch.create_sketch("Top")
    stack.sketch.draw_rectangle(0, 0, PLATE, PLATE)
    stack.sketch.close_sketch()
    assert stack.feature.create_extrude(0.01)["status"] == "created"


def _boss_on_plate(stack, x, y):
    """Cylinder r 5 mm, 10 mm high, standing on the plate top (z = 0.01)."""
    plane = stack.feature.create_ref_plane_by_offset(1, 0.01, "Normal")["new_plane_index"]
    stack.sketch.create_sketch_on_plane_index(plane)
    stack.sketch.draw_circle(x, y, BOSS_R)
    stack.sketch.close_sketch()
    assert stack.feature.create_extrude(BOSS_H)["status"] == "created"
    return stack.feature.list_features()["features"][-1]["name"], plane


def _inside(stack, x, y, z):
    return stack.query.is_point_inside_body(x, y, z)["is_inside"]


class TestFeatureByName:
    def test_delete_by_name_removes_that_feature(self, stack, new_part):
        _plate(stack)
        name, _ = _boss_on_plate(stack, 0.05, 0.05)
        index, err = stack.feature.resolve_feature_index(feature_name=name)
        assert err is None, err
        before = _volume(stack)
        assert stack.feature.delete_feature(index)["status"] == "deleted"
        assert _volume(stack) == pytest.approx(before - BOSS_VOLUME, rel=1e-3)
        assert _inside(stack, 0.1, 0.1, 0.005), "the plate (feature 0) must survive"

    def test_no_target_is_refused(self, stack, new_part):
        _plate(stack)
        index, err = stack.feature.resolve_feature_index()
        assert index is None and err is not None


class TestCircularPattern:
    def test_full_circle_about_an_off_origin_axis(self, stack, new_part):
        _plate(stack)
        name, plane = _boss_on_plate(stack, 0.15, 0.1)
        before = _volume(stack)
        r = stack.feature.create_pattern_circular_ex(name, 4, 360.0, plane, 0.1, 0.1, 0.01)
        assert r.get("status") == "created", r
        assert _volume(stack) == pytest.approx(before + 3 * BOSS_VOLUME, rel=1e-3)
        for x, y in ((0.1, 0.15), (0.05, 0.1), (0.1, 0.05)):
            assert _inside(stack, x, y, 0.015), (x, y)

    def test_partial_angle_places_count_copies(self, stack, new_part):
        """90 deg with 3 copies: instances at 0, 45 and 90 deg (needs ArcPattern True)."""
        _plate(stack)
        name, plane = _boss_on_plate(stack, 0.15, 0.1)
        before = _volume(stack)
        r = stack.feature.create_pattern_circular_ex(name, 3, 90.0, plane, 0.1, 0.1, 0.01)
        assert r.get("status") == "created", r
        assert _volume(stack) == pytest.approx(before + 2 * BOSS_VOLUME, rel=1e-3)
        r45 = 0.05 * math.sqrt(0.5)
        assert _inside(stack, 0.1 + r45, 0.1 + r45, 0.015), "instance at 45 deg"
        assert _inside(stack, 0.1, 0.15, 0.015), "instance at 90 deg (end of the arc)"


class TestOrderedMirror:
    def test_two_features_are_mirrored(self, stack, new_part):
        _plate(stack)
        a, _ = _boss_on_plate(stack, 0.05, 0.05)
        b, _ = _boss_on_plate(stack, 0.05, 0.15)
        before = _volume(stack)
        # Right plane (x = 0) -> copies land at x = -0.05, beside the plate
        r = stack.feature.create_mirror([a, b], 2)
        assert r.get("status") == "created", r
        assert _volume(stack) == pytest.approx(before + 2 * BOSS_VOLUME, rel=1e-3)
        assert _inside(stack, -0.05, 0.05, 0.015) and _inside(stack, -0.05, 0.15, 0.015)


class TestAssembly:
    def test_unground_removes_only_that_components_ground(self, stack, new_assembly, saved_part):
        doc = stack.doc.get_active_document()
        stack.assembly.add_component(str(saved_part))
        stack.assembly.add_component(str(saved_part), 0.3, 0.0, 0.0)

        def grounds():
            rels = doc.Relations3d
            return sorted(
                str(rels.Item(i).Occurrence.Name)
                for i in range(1, rels.Count + 1)
                if rels.Item(i).Type == 1959028688  # igGroundRelation3d
            )

        before = grounds()
        r = stack.assembly.ground_component(1, ground=False)
        assert r.get("status") == "ungrounded", r
        second = str(doc.Occurrences.Item(2).Name)
        assert second not in grounds()
        assert len(grounds()) == len(before) - 1

    def test_interference_found_and_cleared(self, stack, new_assembly, saved_part):
        stack.assembly.add_component(str(saved_part))
        stack.assembly.add_component(str(saved_part), 0.04, 0.0, 0.0)  # half overlap in x
        r = stack.assembly.check_interference()
        assert "error" not in r, r
        print("interference result:", {k: v for k, v in r.items() if k != "report"})
        assert r["interference_count"] >= 1, r

    def test_no_interference_when_apart(self, stack, new_assembly, saved_part):
        stack.assembly.add_component(str(saved_part))
        stack.assembly.add_component(str(saved_part), 0.5, 0.0, 0.0)
        r = stack.assembly.check_interference()
        assert "error" not in r, r
        print("separate parts:", {k: v for k, v in r.items() if k != "report"})
        assert r.get("interference_count", 0) == 0, r


class TestSaveInPlace:
    def test_save_onto_own_file(self, stack, new_part, tmp_path):
        _plate(stack)
        path = tmp_path / "plate.par"
        assert "error" not in stack.doc.save_document(str(path)), "first save"
        r = stack.doc.save_document(str(path), overwrite=True)
        try:
            assert "error" not in r, r
            assert path.exists()
        finally:
            # SaveAs renamed the scratch part, so the fixture will not close it.
            stack.doc.close_document(save=False)
