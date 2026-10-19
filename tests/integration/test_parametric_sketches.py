"""Fully dimensioned sketches built through the MCP tool functions only.

A part is sketched with connected shapes, driving dimensions to the reference
planes and named variables; changing a variable must move the solid. A second
test links a variable from a saved master part into a dependent part and drives
an assembly update from it.

Run with: uv run pytest -m integration
"""

from __future__ import annotations

import contextlib
import json

import pytest

from tests.integration.conftest import _open_document_names

pytestmark = pytest.mark.integration

MM3 = 1e-9  # m^3 per mm^3


@pytest.fixture
def tools(solid_edge, preexisting_documents):
    """The tool modules, wired to a live connection; closes only what they opened."""
    from solidedge_mcp import managers
    from solidedge_mcp.tools import assembly, documents, query, resources, sketching
    from solidedge_mcp.tools.features import _extrude

    result = managers.connection.connect(start_if_needed=False)
    assert result.get("status") == "connected", result
    app = managers.connection.get_application()
    before = _open_document_names(app)

    class Tools:
        pass

    t = Tools()
    t.app = app
    t.documents, t.query, t.sketching, t.assembly = documents, query, sketching, assembly
    t.extrude = _extrude.create_extrude
    t.resources = resources
    yield t

    ours = _open_document_names(app) - before - set(preexisting_documents)
    for i in range(app.Documents.Count, 0, -1):
        with contextlib.suppress(Exception):
            doc = app.Documents.Item(i)
            if doc.Name in ours:
                doc.Close(False)
    managers.doc_manager.active_document = None
    managers.sketch_manager.clear_state()


def _ok(result: dict) -> dict:
    assert "error" not in result, result
    return result


def _volume_mm3(t) -> float:
    props = json.loads(t.resources.geometry_mass_properties(1000))
    return props["volume"] / MM3


def _range(t) -> list[float]:
    box = json.loads(t.resources.geometry_bounding_box())
    return [*box["min"], *box["max"]]


class TestADimensionedPartFollowsItsVariables:
    def test_changing_a_variable_moves_the_solid(self, tools):
        t = tools
        _ok(t.documents.create_document(type="part"))
        _ok(t.query.manage_variable(action="add", name="Breite", formula="40", units_type=1))

        _ok(t.sketching.manage_sketch(action="create", plane="Top"))
        rect = _ok(t.sketching.draw(shape="rectangle", x1=0.004, y1=0.006, x2=0.05, y2=0.03))
        bottom, right, _top, left = rect["elements"]

        length = _ok(
            t.sketching.sketch_dimension(
                type="length", elements=[bottom], name="Laenge", formula="Breite"
            )
        )
        assert length["variable"] == "Laenge"
        assert length["value"] == pytest.approx(0.04)
        height = _ok(
            t.sketching.sketch_dimension(type="length", elements=[right], value=0.02, name="Hoehe")
        )
        assert height["value"] == pytest.approx(0.02)
        to_front = _ok(
            t.sketching.sketch_dimension(
                type="distance", elements=[bottom, ["ref", 3]], value=0.005, name="Abstand_Y"
            )
        )
        assert to_front["axis"] == "y"
        to_right = _ok(
            t.sketching.sketch_dimension(
                type="distance", elements=[left, ["ref", 2]], value=0.005, name="Abstand_X"
            )
        )
        assert to_right["axis"] == "x"

        closed = _ok(t.sketching.manage_sketch(action="close"))
        assert closed["validation_code"] == 0
        _ok(t.extrude(method="finite", distance=0.01))
        assert _volume_mm3(t) == pytest.approx(40 * 20 * 10, rel=1e-6)
        assert _range(t)[:2] == pytest.approx([0.005, 0.005])

        _ok(t.query.manage_variable(action="set_formula", name="Breite", formula="60"))
        assert _volume_mm3(t) == pytest.approx(60 * 20 * 10, rel=1e-6)
        box = _range(t)
        assert box[0] == pytest.approx(0.005)
        assert box[3] == pytest.approx(0.065)

        _ok(t.query.manage_variable(action="set", name="Hoehe", value=0.03))
        assert _volume_mm3(t) == pytest.approx(60 * 30 * 10, rel=1e-6)

        _ok(t.query.manage_variable(action="set", name="Abstand_X", value=0.01))
        assert _range(t)[0] == pytest.approx(0.01)

    def test_a_dimension_added_after_the_feature_rolls_the_model_forward(self, tools):
        t = tools
        _ok(t.documents.create_document(type="part"))
        _ok(t.sketching.manage_sketch(action="create", plane="Top"))
        rect = _ok(t.sketching.draw(shape="rectangle", x1=0.0, y1=0.0, x2=0.04, y2=0.02))
        _ok(t.sketching.manage_sketch(action="close"))
        _ok(t.extrude(method="finite", distance=0.01))
        assert _volume_mm3(t) == pytest.approx(8000, rel=1e-6)

        result = _ok(
            t.sketching.sketch_dimension(type="length", elements=[rect["elements"][0]], value=0.03)
        )

        assert result["model_recomputed"] is True
        assert _volume_mm3(t) == pytest.approx(6000, rel=1e-6)


class TestDimensionKinds:
    def test_each_kind_reports_what_it_measures(self, tools):
        t = tools
        _ok(t.documents.create_document(type="part"))
        _ok(t.sketching.manage_sketch(action="create", plane="Top"))
        rect = _ok(t.sketching.draw(shape="rectangle", x1=0.01, y1=0.01, x2=0.05, y2=0.04))
        bottom, right, top, _left = rect["elements"]
        circle = _ok(t.sketching.draw(shape="circle", center_x=0.03, center_y=0.025, radius=0.005))
        arc = _ok(
            t.sketching.draw(
                shape="arc", center_x=0.08, center_y=0.0, radius=0.01, start_angle=0, end_angle=90
            )
        )

        aligned = _ok(
            t.sketching.sketch_dimension(
                type="distance", elements=[bottom, top], keypoint1=0, keypoint2=0
            )
        )
        assert aligned["axis"] == "aligned"
        assert aligned["measured"] == pytest.approx(0.05)  # (0.01,0.01)-(0.05,0.04)
        along_x = _ok(
            t.sketching.sketch_dimension(
                type="distance", elements=[bottom, top], keypoint1=0, keypoint2=1, axis="x"
            )
        )
        assert along_x["measured"] == pytest.approx(0.0)
        along_y = _ok(
            t.sketching.sketch_dimension(
                type="distance", elements=[bottom, top], keypoint1=1, keypoint2=0, axis="y"
            )
        )
        assert along_y["measured"] == pytest.approx(0.03)

        diameter = _ok(
            t.sketching.sketch_dimension(type="diameter", elements=[circle["element"]], value=0.012)
        )
        assert diameter["value"] == pytest.approx(0.012)
        centre_x = _ok(
            t.sketching.sketch_dimension(type="distance", elements=[circle["element"], ["ref", 2]])
        )
        assert (centre_x["axis"], centre_x["measured"]) == ("x", pytest.approx(0.03))
        centre_y = _ok(
            t.sketching.sketch_dimension(type="distance", elements=[circle["element"], ["ref", 3]])
        )
        assert (centre_y["axis"], centre_y["measured"]) == ("y", pytest.approx(0.025))

        radius = _ok(
            t.sketching.sketch_dimension(type="radius", elements=[arc["element"]], value=0.015)
        )
        assert radius["value"] == pytest.approx(0.015)

        angle = _ok(t.sketching.sketch_dimension(type="angle", elements=[bottom, right]))
        assert angle["measured"] == pytest.approx(90)

    def test_keypoint_relations_tie_shapes_to_the_reference_planes(self, tools):
        t = tools
        _ok(t.documents.create_document(type="part"))
        _ok(t.sketching.manage_sketch(action="create", plane="Top"))
        rect = _ok(t.sketching.draw(shape="rectangle", x1=0.002, y1=0.003, x2=0.04, y2=0.02))
        bottom, _right, _top, left = rect["elements"]
        _ok(
            t.sketching.sketch_constraint(
                type="geometric", constraint_type="Colinear", elements=[bottom, ["ref", 3]]
            )
        )
        _ok(
            t.sketching.sketch_constraint(
                type="geometric",
                constraint_type="PointOn",
                elements=[left, ["ref", 2]],
                keypoint1=0,
            )
        )
        _ok(t.sketching.manage_sketch(action="close"))
        _ok(t.extrude(method="finite", distance=0.01))

        box = _range(t)
        assert box[0] == pytest.approx(0.0, abs=1e-9)
        assert box[1] == pytest.approx(0.0, abs=1e-9)


class TestLinkedVariables:
    def test_a_master_part_drives_a_dependent_part_in_an_assembly(self, tools, tmp_path):
        t = tools
        master_path = str(tmp_path / "master.par")
        part_path = str(tmp_path / "teil.par")
        asm_path = str(tmp_path / "baugruppe.asm")

        _ok(t.documents.create_document(type="part"))
        _ok(t.query.manage_variable(action="add", name="W", formula="40", units_type="length"))
        _ok(t.documents.save_document(file_path=master_path))
        master_name = t.app.ActiveDocument.Name

        _ok(t.documents.create_document(type="part"))
        part_name = t.app.ActiveDocument.Name
        _ok(t.documents.activate_document(name_or_index=master_name))
        copied = t.query.manage_variable(action="copy_clipboard", name="W")
        if copied.get("hresult") == "0x800401D0":
            pytest.skip("another program holds the Windows clipboard open")
        _ok(copied)
        _ok(t.documents.activate_document(name_or_index=part_name))
        linked = _ok(
            t.query.manage_variable(action="add_from_clipboard", name="W", units_type="length")
        )
        assert linked["formula"].startswith("@"), linked
        assert linked["value"] == pytest.approx(0.04)

        _ok(t.sketching.manage_sketch(action="create", plane="Top"))
        rect = _ok(t.sketching.draw(shape="rectangle", x1=0.0, y1=0.0, x2=0.03, y2=0.02))
        bottom = rect["elements"][0]
        _ok(t.sketching.sketch_dimension(type="length", elements=[bottom], formula="W"))
        _ok(t.sketching.manage_sketch(action="close"))
        _ok(t.extrude(method="finite", distance=0.01))
        assert _volume_mm3(t) == pytest.approx(40 * 20 * 10, rel=1e-6)
        _ok(t.documents.save_document(file_path=part_path))
        _ok(t.documents.close_document(save=False))
        _ok(t.documents.activate_document(name_or_index=master_name))
        _ok(t.documents.close_document(save=False))

        _ok(t.documents.create_document(type="assembly"))
        _ok(t.assembly.add_assembly_component(file_path=master_path))
        _ok(t.assembly.add_assembly_component(file_path=part_path))
        _ok(t.documents.save_document(file_path=asm_path))
        asm_name = t.app.ActiveDocument.Name

        _ok(t.documents.open_document(file_path=master_path))
        _ok(t.query.manage_variable(action="set_formula", name="W", formula="60"))
        _ok(t.documents.save_document())
        _ok(t.documents.close_document(save=False))
        _ok(t.documents.activate_document(name_or_index=asm_name))
        _ok(t.assembly.assembly_feature(type="recompute"))

        occurrences = t.app.ActiveDocument.Occurrences
        volumes = {
            occurrences.Item(i).Name: occurrences.Item(i).OccurrenceDocument.Models.Item(1)
            for i in range(1, occurrences.Count + 1)
            if occurrences.Item(i).OccurrenceDocument.Models.Count
        }
        (model,) = volumes.values()
        assert model.Body.Volume / MM3 == pytest.approx(60 * 20 * 10, rel=1e-6)
