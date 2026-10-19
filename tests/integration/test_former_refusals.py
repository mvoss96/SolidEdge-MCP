"""Tools that used to refuse as unsupported and now build, driven live.

Each test checks the effect in Solid Edge or on disk, not only the status.

Run with: uv run pytest -m integration
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestConvertByFilePath:
    def test_a_saved_part_is_written_as_step_and_closed_again(
        self, stack, solid_edge, saved_part, tmp_path
    ):
        app = solid_edge.get_application()
        before = app.Documents.Count
        out = tmp_path / "box.stp"

        result = stack.connection.convert_by_file_path(str(saved_part), str(out))

        assert result.get("status") == "converted", result
        assert out.exists() and out.stat().st_size > 1000
        assert out.read_text(errors="ignore").startswith("ISO-10303-21")
        assert app.Documents.Count == before


class TestSelectAll:
    def test_a_part_selects_every_feature_tree_entry(self, stack, new_part):
        stack.sketch.create_sketch("Top")
        stack.sketch.draw_rectangle(0, 0, 0.04, 0.02)
        stack.sketch.close_sketch()
        assert stack.feature.create_extrude(0.01).get("status") == "created"
        doc = stack.doc.get_active_document()

        r = stack.query.select_all()

        assert r.get("status") == "selected", r
        assert r["count"] == doc.DesignEdgebarFeatures.Count == doc.SelectSet.Count >= 4

    def test_an_assembly_selects_every_occurrence(self, stack, saved_part, new_assembly):
        for _ in range(2):
            assert "error" not in stack.assembly.add_component(str(saved_part))
        doc = stack.doc.get_active_document()

        r = stack.query.select_all()

        assert r == {"status": "selected", "count": 2, "selected": "occurrences"}, r
        assert doc.SelectSet.Count == 2


def _box(stack, height=0.03):
    stack.sketch.create_sketch("Top")
    stack.sketch.draw_rectangle(0, 0, 0.08, 0.048)
    stack.sketch.close_sketch()
    assert stack.feature.create_extrude(height)["status"] == "created"


def _volume(stack):
    return stack.doc.get_active_document().Models.Item(1).Body.Volume


class TestFiniteNormalCutout:
    def test_a_part_loses_the_cut_cylinder(self, stack, new_part):
        _box(stack)
        before = _volume(stack)
        stack.sketch.create_sketch("Top")
        stack.sketch.draw_circle(0.02, 0.02, 0.004)
        stack.sketch.close_sketch()

        r = stack.feature.create_normal_cutout(0.01)

        assert r.get("status") == "created", r
        removed = before - _volume(stack)
        assert removed == pytest.approx(3.141592653589793 * 0.004**2 * 0.01, rel=1e-3)


def _tab_and_edge(stack):
    """An ordered 80 x 48 mm base tab and a (face, edge) pair on a long edge of its top or
    bottom face. AddFlangeByFace takes that face as its reference; a thin side face
    answers E_POINTER."""
    from tests.integration.test_synchronous_flange_split_thicken import _tab

    _tab(stack)
    faces = stack.doc.get_active_document().Models.Item(1).Body.Faces(1)
    for fi in range(1, faces.Count + 1):
        face = faces.Item(fi)
        if face.Area < 0.003:
            continue
        edges = face.Edges
        for ei in range(1, edges.Count + 1):
            sp = edges.Item(ei).StartVertex.GetPointData([0.0] * 3)
            ep = edges.Item(ei).EndVertex.GetPointData([0.0] * 3)
            if abs(sp[0] - ep[0]) > 0.05:  # runs along X, 80 mm
                return fi - 1, ei - 1
    raise AssertionError("no long edge on a sheet face")


class TestOrderedFlanges:
    @pytest.mark.parametrize(
        "method, extra",
        [
            ("create_flange", {"inside_radius": 0.003, "bend_angle": 45.0}),
            ("create_flange_by_match_face", {}),
            ("create_flange_with_bend_calc", {"bend_deduction": 0.0005}),
            ("create_flange_match_face_with_bend", {}),
            ("create_flange_by_face", {"ref_face_index": None}),
            ("create_flange_by_face_with_bend", {"ref_face_index": None}),
        ],
    )
    def test_an_ordered_tab_gets_a_solved_flange(self, stack, new_sheet_metal, method, extra):
        fi, ei = _tab_and_edge(stack)
        doc = stack.doc.get_active_document()
        assert doc.ModelingMode == 2  # ordered
        before = doc.Models.Item(1).Body.Volume
        if "ref_face_index" in extra:
            extra = {**extra, "ref_face_index": fi}

        r = getattr(stack.feature, method)(fi, ei, flange_length=0.02, **extra)

        assert r.get("status") == "created", r
        flange = doc.Models.Item(1).Flanges.Item(1)
        assert flange.Status[0] == 1216476310  # igFeatureOK
        assert doc.Models.Item(1).Body.Volume > before
        if method == "create_flange":
            assert flange.BendRadius == pytest.approx(0.003)
            assert flange.BendAngle == pytest.approx(0.7853981633974483)
        if method == "create_flange_with_bend_calc":
            assert flange.GetBendCalculationMethodAndValue() == (1, pytest.approx(0.0005))


class TestLouver:
    @pytest.mark.parametrize("direction", ["Normal", "Reverse"])
    def test_a_line_on_the_sheet_plane_forms_a_louver(self, stack, new_sheet_metal, direction):
        from tests.integration.test_synchronous_flange_split_thicken import _tab

        _tab(stack)
        doc = stack.doc.get_active_document()
        faces_before = doc.Models.Item(1).Body.Faces(1).Count
        stack.sketch.create_sketch("Top")
        stack.sketch.draw_line(0.02, 0.024, 0.06, 0.024)
        stack.sketch.close_sketch(closed=False)

        r = stack.feature.create_louver(0.006, direction, height=0.004)

        assert r.get("status") == "created", r
        louver = doc.Models.Item(1).Louvers.Item(1)
        assert louver.Status[0] == 1216476310  # igFeatureOK
        assert doc.Models.Item(1).Body.Faces(1).Count > faces_before


def _two_circle_sections(stack):
    """Circles of 10 and 15 mm radius on Top and on a plane 30 mm above it."""
    assert stack.feature.create_ref_plane_by_offset(1, 0.03)["status"] == "created"
    for plane, radius in ((1, 0.01), (4, 0.015)):
        stack.sketch.create_sketch_on_plane_index(plane)
        stack.sketch.draw_circle(0.0, 0.0, radius)
        stack.sketch.close_sketch()


class TestLoftedSurface:
    @pytest.mark.parametrize("method", ["create_lofted_surface", "create_lofted_surface_v2"])
    def test_two_circles_give_a_solved_surface(self, stack, new_part, method):
        _two_circle_sections(stack)
        surfaces = stack.doc.get_active_document().Constructions.LoftedSurfaces

        r = getattr(stack.feature, method)()

        assert r.get("status") == "created", r
        assert surfaces.Count == 1
        assert surfaces.Item(1).Status[0] == 1216476310  # igFeatureOK


class TestWire:
    def test_a_wire_runs_along_a_path_through_space_points(self, stack, saved_part, new_assembly):
        assert "error" not in stack.assembly.add_component(str(saved_part))
        doc = stack.doc.get_active_document()

        r = stack.assembly.add_wire(
            [], [], "W1", path_points=[[0.0, 0.0, 0.05], [0.1, 0.0, 0.05], [0.1, 0.05, 0.05]]
        )

        assert r.get("status") == "created", r
        assert doc.Paths.Count == 1
        assert doc.Harnesses.Item(1).Wires.Count == 1
