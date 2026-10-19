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
