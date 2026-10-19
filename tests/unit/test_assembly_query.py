"""
Unit tests for AssemblyManager query backend methods.

Tests query mixin: GetOccurrenceBoundingBox, GetBom, GetDocumentTree,
GetComponentDisplayName, GetOccurrenceDocument, GetSubOccurrences,
CheckInterference, IsSubassembly, GetOccurrenceBodies,
GetOccurrenceStyle, GetFaceStyle, GetOccurrence.
Uses unittest.mock to simulate COM objects.
"""

import math
import os
from unittest.mock import MagicMock

import pytest

from solidedge_mcp.backends.constants import DocumentTypeConstants

IG_ASSEMBLY_DOCUMENT = DocumentTypeConstants.igAssemblyDocument
IG_DRAFT_DOCUMENT = DocumentTypeConstants.igDraftDocument
IG_PART_DOCUMENT = DocumentTypeConstants.igPartDocument


@pytest.fixture
def asm_mgr():
    """Create AssemblyManager with mocked dependencies."""
    from solidedge_mcp.backends.assembly import AssemblyManager

    dm = MagicMock()
    doc = MagicMock()
    doc.Type = IG_ASSEMBLY_DOCUMENT
    dm.get_active_document.return_value = doc
    return AssemblyManager(dm), doc


@pytest.fixture
def asm_mgr_with_sketch():
    """Create AssemblyManager with mocked doc and sketch manager."""
    from solidedge_mcp.backends.assembly import AssemblyManager

    dm = MagicMock()
    sm = MagicMock()
    doc = MagicMock()
    doc.Type = IG_ASSEMBLY_DOCUMENT
    dm.get_active_document.return_value = doc
    return AssemblyManager(dm, sm), doc, sm


# ============================================================================
# OCCURRENCE BOUNDING BOX
# ============================================================================


class TestGetOccurrenceBoundingBox:
    def test_success(self, asm_mgr):
        """GetRangeBox returns the points; it does not fill the buffers.

        This test used to mock it as mutating its arguments, which is not what
        pywin32 does with an [in,out] SAFEARRAY. Real components therefore came
        back with a zero-sized box, verified against Solid Edge 2026.
        """
        am, doc = asm_mgr
        occ = MagicMock()
        occ.GetRangeBox.return_value = ((0.0, 0.0, 0.0), (0.1, 0.2, 0.3))

        occurrences = MagicMock()
        occurrences.Count = 2
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        result = am.get_occurrence_bounding_box(0)
        assert result["component_index"] == 0
        assert result["min"] == [0.0, 0.0, 0.0]
        assert result["max"] == [0.1, 0.2, 0.3]
        assert result["size"] == pytest.approx([0.1, 0.2, 0.3])
        # Two plain lists, sized 3, and nothing else.
        args, kwargs = occ.GetRangeBox.call_args
        assert args == ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        assert not kwargs

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        del doc.Occurrences  # Remove attribute

        result = am.get_occurrence_bounding_box(0)
        assert "error" in result

    def test_invalid_index(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 2
        doc.Occurrences = occurrences

        result = am.get_occurrence_bounding_box(5)
        assert "error" in result


# ============================================================================
# BOM
# ============================================================================


class TestGetBom:
    def test_basic_bom(self, asm_mgr):
        am, doc = asm_mgr

        occ1 = MagicMock()
        occ1.OccurrenceFileName = "C:/parts/bolt.par"
        occ1.Name = "Bolt_1"
        occ1.IncludeInBom = True
        occ1.IsPatternItem = False

        occ2 = MagicMock()
        occ2.OccurrenceFileName = "C:/parts/bolt.par"
        occ2.Name = "Bolt_2"
        occ2.IncludeInBom = True
        occ2.IsPatternItem = False

        occ3 = MagicMock()
        occ3.OccurrenceFileName = "C:/parts/plate.par"
        occ3.Name = "Plate_1"
        occ3.IncludeInBom = True
        occ3.IsPatternItem = False

        occurrences = MagicMock()
        occurrences.Count = 3
        occurrences.Item.side_effect = lambda i: [None, occ1, occ2, occ3][i]
        doc.Occurrences = occurrences

        result = am.get_bom()
        assert result["total_occurrences"] == 3
        assert result["unique_parts"] == 2

        # Find bolt and plate in BOM
        bolt = next(b for b in result["bom"] if "bolt" in b["file_path"])
        plate = next(b for b in result["bom"] if "plate" in b["file_path"])
        assert bolt["quantity"] == 2
        assert plate["quantity"] == 1

    def test_excludes_non_bom_items(self, asm_mgr):
        am, doc = asm_mgr

        occ1 = MagicMock()
        occ1.OccurrenceFileName = "C:/parts/bolt.par"
        occ1.Name = "Bolt_1"
        occ1.IncludeInBom = True
        occ1.IsPatternItem = False

        occ2 = MagicMock()
        occ2.OccurrenceFileName = "C:/parts/ref.par"
        occ2.Name = "Reference_1"
        occ2.IncludeInBom = False
        occ2.IsPatternItem = False

        occurrences = MagicMock()
        occurrences.Count = 2
        occurrences.Item.side_effect = lambda i: [None, occ1, occ2][i]
        doc.Occurrences = occurrences

        result = am.get_bom()
        assert result["unique_parts"] == 1
        assert result["bom"][0]["name"] == "Bolt_1"

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.get_bom()
        assert "error" in result

    def test_empty_assembly(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 0
        doc.Occurrences = occurrences

        result = am.get_bom()
        assert result["total_occurrences"] == 0
        assert result["unique_parts"] == 0
        assert result["bom"] == []


# ============================================================================
# DOCUMENT TREE
# ============================================================================


class TestGetDocumentTree:
    def test_flat_assembly(self, asm_mgr):
        am, doc = asm_mgr

        occ1 = MagicMock()
        occ1.Name = "Part_1"
        occ1.OccurrenceFileName = "C:/parts/part1.par"
        occ1.Visible = True
        occ1.SubOccurrences.Count = 0

        occ2 = MagicMock()
        occ2.Name = "Part_2"
        occ2.OccurrenceFileName = "C:/parts/part2.par"
        occ2.Visible = True
        occ2.SubOccurrences.Count = 0

        occurrences = MagicMock()
        occurrences.Count = 2
        occurrences.Item.side_effect = lambda i: [None, occ1, occ2][i]
        doc.Occurrences = occurrences
        doc.Name = "Assembly.asm"

        result = am.get_document_tree()
        assert result["top_level_count"] == 2
        assert result["tree"][0]["name"] == "Part_1"
        assert result["tree"][1]["file"] == "C:/parts/part2.par"

    def test_nested_assembly(self, asm_mgr):
        am, doc = asm_mgr

        # Sub-occurrence
        sub_occ = MagicMock()
        sub_occ.Name = "SubPart_1"
        sub_occ.OccurrenceFileName = "C:/parts/sub.par"
        sub_occ.Visible = True
        sub_occs = MagicMock()
        sub_occs.Count = 0
        sub_occ.SubOccurrences = sub_occs

        # Top-level occurrence with children
        occ1 = MagicMock()
        occ1.Name = "SubAsm_1"
        occ1.OccurrenceFileName = "C:/asm/sub.asm"
        occ1.Visible = True
        sub_occs_parent = MagicMock()
        sub_occs_parent.Count = 1
        sub_occs_parent.Item.return_value = sub_occ
        occ1.SubOccurrences = sub_occs_parent

        occurrences = MagicMock()
        occurrences.Count = 1
        occurrences.Item.return_value = occ1
        doc.Occurrences = occurrences
        doc.Name = "TopAsm.asm"

        result = am.get_document_tree()
        assert result["top_level_count"] == 1
        assert result["tree"][0]["name"] == "SubAsm_1"
        assert len(result["tree"][0]["children"]) == 1
        assert result["tree"][0]["children"][0]["name"] == "SubPart_1"

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.get_document_tree()
        assert "error" in result


# ============================================================================
# ASSEMBLY: GET COMPONENT DISPLAY NAME
# ============================================================================


class TestGetComponentDisplayName:
    def test_success(self, asm_mgr):
        am, doc = asm_mgr
        occ = MagicMock()
        # Occurrence has no DisplayName; Name is what Solid Edge shows.
        del occ.DisplayName
        occ.Name = "Bolt_1"
        occ.OccurrenceFileName = "C:/parts/bolt.par"
        occurrences = MagicMock()
        occurrences.Count = 2
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        result = am.get_component_display_name(0)
        assert result["display_name"] == "Bolt_1"
        assert result["name"] == "Bolt_1"
        assert result["file_name"] == "C:/parts/bolt.par"

    def test_invalid_index(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        doc.Occurrences = occurrences

        result = am.get_component_display_name(5)
        assert "error" in result

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.get_component_display_name(0)
        assert "error" in result


# ============================================================================
# ASSEMBLY: GET OCCURRENCE DOCUMENT
# ============================================================================


class TestGetOccurrenceDocument:
    def test_success(self, asm_mgr):
        am, doc = asm_mgr
        occ_doc = MagicMock()
        occ_doc.Name = "bolt.par"
        occ_doc.FullName = "C:/parts/bolt.par"
        occ_doc.Type = 1
        occ_doc.ReadOnly = False

        occ = MagicMock()
        occ.OccurrenceDocument = occ_doc
        occ.OccurrenceFileName = "C:/parts/bolt.par"
        occurrences = MagicMock()
        occurrences.Count = 1
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        result = am.get_occurrence_document(0)
        assert result["document_name"] == "bolt.par"
        assert result["full_name"] == "C:/parts/bolt.par"
        # A bare 1 does not say "part"; the name leads and the code follows.
        assert result["type"] == "part"
        assert result["type_code"] == 1
        assert result["read_only"] is False

    def test_invalid_index(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        doc.Occurrences = occurrences

        result = am.get_occurrence_document(5)
        assert "error" in result

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.get_occurrence_document(0)
        assert "error" in result


# ============================================================================
# ASSEMBLY: GET SUB-OCCURRENCES
# ============================================================================


class TestGetSubOccurrences:
    def test_with_children(self, asm_mgr):
        am, doc = asm_mgr
        # A SubOccurrence names its file SubOccurrenceFileName;
        # OccurrenceFileName is on Occurrence, so the key was always missing.
        child1 = MagicMock()
        child1.Name = "SubPart_1"
        child1.SubOccurrenceFileName = "C:/parts/sub1.par"
        del child1.OccurrenceFileName

        child2 = MagicMock()
        child2.Name = "SubPart_2"
        child2.SubOccurrenceFileName = "C:/parts/sub2.par"
        del child2.OccurrenceFileName

        sub_occs = MagicMock()
        sub_occs.Count = 2
        sub_occs.Item.side_effect = lambda i: {1: child1, 2: child2}[i]

        occ = MagicMock()
        occ.SubOccurrences = sub_occs
        occurrences = MagicMock()
        occurrences.Count = 1
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        result = am.get_sub_occurrences(0)
        assert result["count"] == 2
        assert result["sub_occurrences"][0]["name"] == "SubPart_1"
        assert result["sub_occurrences"][1]["file"] == "C:/parts/sub2.par"

    def test_no_children(self, asm_mgr):
        am, doc = asm_mgr
        sub_occs = MagicMock()
        sub_occs.Count = 0

        occ = MagicMock()
        occ.SubOccurrences = sub_occs
        occurrences = MagicMock()
        occurrences.Count = 1
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        result = am.get_sub_occurrences(0)
        assert result["count"] == 0
        assert result["sub_occurrences"] == []

    def test_invalid_index(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        doc.Occurrences = occurrences

        result = am.get_sub_occurrences(5)
        assert "error" in result

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.get_sub_occurrences(0)
        assert "error" in result


# ============================================================================
# INTERFERENCE CHECK
# ============================================================================


_GERMAN_REPORT = """Auszugsname: C:/Temp/report.txt
Auszugszeit 19.10.2026 15:38:54
Auszugsoptionen:
    Teilnamen
    Kollisionsvolumen

Auswahlsatz 1:
    rahmen.par:1
    sattel.par:1
    laufrad.par:2

Kollisionen:
    1 von 2
    rahmen.par:1
    sattel.par:1
    Kollisionsvolumen 1.197 mm^3
    Kollisionsvolumen 0.000 mm^3

    2 von 2
    rahmen.par:1
    laufrad.par:2
    Kollisionsvolumen 504.231 mm^3
    (Wahrscheinliche Kollision)

    2 Kollisionen festgestellt
"""


class TestParseInterferenceReport:
    def test_reads_blocks_by_structure_not_by_label(self):
        from solidedge_mcp.backends.assembly._query import parse_interference_report

        blocks = parse_interference_report(
            _GERMAN_REPORT, ["rahmen.par:1", "sattel.par:1", "laufrad.par:2"]
        )

        assert [b["parts"] for b in blocks] == [
            ["rahmen.par:1", "sattel.par:1"],
            ["rahmen.par:1", "laufrad.par:2"],
        ]
        assert blocks[0]["volumes"] == [1.197, 0.0]
        assert blocks[0]["total_volume"] == pytest.approx(1.197)
        assert blocks[1]["volume_unit"] == "mm^3"
        assert blocks[1]["notes"] == ["(Wahrscheinliche Kollision)"]

    def test_an_english_report_parses_the_same_way(self):
        from solidedge_mcp.backends.assembly._query import parse_interference_report

        text = "Interferences:\n    1 of 1\n    a.par:1\n    b.par:1\n    Volume 2,5 mm^3\n"

        (block,) = parse_interference_report(text, ["a.par:1", "b.par:1"])

        assert block["parts"] == ["a.par:1", "b.par:1"]
        assert block["volumes"] == [2.5]

    def test_a_nested_occurrence_name_counts_as_a_part(self):
        from solidedge_mcp.backends.assembly._query import parse_interference_report

        text = "    1 of 1\n    sub.asm:1/a.par:1\n    b.par:1\n"

        (block,) = parse_interference_report(text, ["b.par:1"])

        assert block["parts"] == ["sub.asm:1/a.par:1", "b.par:1"]

    def test_a_report_without_blocks_has_no_interferences(self):
        from solidedge_mcp.backends.assembly._query import parse_interference_report

        assert parse_interference_report("Kollisionen:\n    Keine\n", ["a.par:1"]) == []


class TestCheckInterference:
    @pytest.fixture
    def assembly(self, asm_mgr, tmp_path, monkeypatch):
        """Three occurrences; Invoke writes the German report and sets Status."""
        import pythoncom

        from solidedge_mcp.backends.assembly import _query

        monkeypatch.setattr(_query.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))
        am, doc = asm_mgr
        occs = []
        for name in ("rahmen.par:1", "sattel.par:1", "laufrad.par:2"):
            occ = MagicMock()
            occ.Name = name
            occs.append(occ)
        occurrences = MagicMock()
        occurrences.Count = 3
        occurrences.Item.side_effect = lambda i: occs[i - 1]
        doc.Occurrences = occurrences

        seen = {}

        def invoke(*args):
            report_path = args[11]
            seen["existed"] = os.path.exists(report_path)
            with open(report_path, "w", encoding="utf-8-sig") as f:
                f.write(_GERMAN_REPORT)
            args[6].value = 5
            seen["args"] = args

        doc._oleobj_.GetIDsOfNames.return_value = 24579
        doc._oleobj_.Invoke.side_effect = invoke
        return am, doc, occs, seen, pythoncom

    def test_all_components_are_checked_against_each_other(self, assembly):
        am, doc, occs, seen, pythoncom = assembly

        result = am.check_interference()

        doc._oleobj_.GetIDsOfNames.assert_called_once_with(0, "CheckInterference")
        args = seen["args"]
        assert args[:5] == (24579, 0, pythoncom.DISPATCH_METHOD, True, 3)
        assert args[5].varianttype == pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH
        assert list(args[5].value) == occs
        assert args[6].varianttype == pythoncom.VT_BYREF | pythoncom.VT_I4
        assert args[7] == 4  # seInterferenceComparisonSet1vsItself
        assert args[8] is pythoncom.ArgNotFound
        assert args[9] is pythoncom.ArgNotFound
        assert args[10] is False
        assert args[12] == 1 | 8  # part names + interference volume
        assert len(args) == 13  # the [out] arrays are omitted
        assert seen["existed"] is False

        assert result["status"] == "interference"
        assert result["interference_count"] == 2
        assert result["check_status"] == "incomplete"
        assert result["check_status_code"] == 5
        assert result["interferences"][1]["parts"] == ["rahmen.par:1", "laufrad.par:2"]
        assert "Kollisionen:" in result["report"]
        assert result["report_path"] == args[11]

    def test_one_component_is_checked_against_all_others(self, assembly):
        am, doc, occs, seen, pythoncom = assembly

        am.check_interference(component_index=1)

        args = seen["args"]
        assert args[4] == 1
        assert list(args[5].value) == [occs[1]]
        assert args[7] == 2  # seInterferenceComparisonSet1vsAllOther

    def test_no_report_means_no_interferences(self, assembly):
        am, doc, _occs, _seen, _pythoncom = assembly

        def invoke(*args):
            args[6].value = 1

        doc._oleobj_.Invoke.side_effect = invoke

        result = am.check_interference()

        assert result["status"] == "no_interference"
        assert result["check_status"] == "none"
        assert result["report"] is None

    def test_a_com_error_is_reported(self, assembly):
        am, doc, _occs, _seen, _pythoncom = assembly
        doc._oleobj_.Invoke.side_effect = Exception("E_INVALIDARG")

        result = am.check_interference()

        assert "error" in result

    def test_invalid_index_still_validated(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 2
        doc.Occurrences = occurrences

        result = am.check_interference(99)
        assert "Invalid component index" in result["error"]

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.check_interference()
        assert "error" in result

    def test_too_few_components(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        doc.Occurrences = occurrences

        result = am.check_interference()
        assert result["status"] == "no_interference"

    def test_invalid_component_index(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 3
        doc.Occurrences = occurrences

        result = am.check_interference(component_index=10)
        assert "error" in result


# ============================================================================
# ASSEMBLY: IS SUBASSEMBLY
# ============================================================================


class TestIsSubassembly:
    def test_true(self, asm_mgr):
        am, doc = asm_mgr
        occ = MagicMock()
        occ.Subassembly = True
        occ.Name = "SubAsm_1"
        occurrences = MagicMock()
        occurrences.Count = 2
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        result = am.is_subassembly(0)
        assert result["is_subassembly"] is True
        assert result["name"] == "SubAsm_1"

    def test_false(self, asm_mgr):
        am, doc = asm_mgr
        occ = MagicMock()
        occ.Subassembly = False
        occ.Name = "Part_1"
        occurrences = MagicMock()
        occurrences.Count = 1
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        result = am.is_subassembly(0)
        assert result["is_subassembly"] is False

    def test_invalid_index(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        doc.Occurrences = occurrences

        result = am.is_subassembly(5)
        assert "error" in result

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.is_subassembly(0)
        assert "error" in result


# ============================================================================
# BATCH 8: GET OCCURRENCE BODIES
# ============================================================================


class TestGetOccurrenceBodies:
    """Occurrence.Bodies does not exist; Body is singular."""

    def _assembly(self, doc, occurrence):
        occurrences = MagicMock()
        occurrences.Count = 2
        occurrences.Item.return_value = occurrence
        doc.Occurrences = occurrences

    def test_reports_the_single_body(self, asm_mgr):
        am, doc = asm_mgr
        body = MagicMock()
        body.Name = "Body_1"
        body.Volume = 0.001
        body.IsSolid = True
        occ = MagicMock()
        occ.Body = body
        del occ.Bodies
        occ.GetSimplifiedBodies.side_effect = Exception("no simplified bodies")
        self._assembly(doc, occ)

        result = am.get_occurrence_bodies(0)

        assert result["body_count"] == 1
        assert result["bodies"][0]["name"] == "Body_1"
        assert result["bodies"][0]["volume"] == 0.001
        assert result["bodies"][0]["is_solid"] is True

    def test_adds_the_simplified_bodies(self, asm_mgr):
        am, doc = asm_mgr
        main = MagicMock()
        main.Name = "Body_1"
        extra = MagicMock()
        extra.Name = "Body_2"
        occ = MagicMock()
        occ.Body = main
        del occ.Bodies
        occ.GetSimplifiedBodies.return_value = (1, (extra,))
        self._assembly(doc, occ)

        result = am.get_occurrence_bodies(0)

        assert [b["name"] for b in result["bodies"]] == ["Body_1", "Body_2"]

    def test_a_component_with_no_body(self, asm_mgr):
        am, doc = asm_mgr
        occ = MagicMock()
        occ.Body = None
        del occ.Bodies
        occ.GetSimplifiedBodies.side_effect = Exception("none")
        self._assembly(doc, occ)

        result = am.get_occurrence_bodies(0)

        assert result["body_count"] == 0

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        assert "error" in am.get_occurrence_bodies(0)

    def test_invalid_index(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        doc.Occurrences = occurrences

        assert "error" in am.get_occurrence_bodies(5)


# ============================================================================
# BATCH 8: GET OCCURRENCE STYLE
# ============================================================================


class TestGetOccurrenceStyle:
    def test_success(self, asm_mgr):
        am, doc = asm_mgr
        occ = MagicMock()
        occ.Style = "Steel"
        occurrences = MagicMock()
        occurrences.Count = 2
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        result = am.get_occurrence_style(0)
        assert result["component_index"] == 0
        assert result["style"] == "Steel"

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.get_occurrence_style(0)
        assert "error" in result

    def test_invalid_index(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        doc.Occurrences = occurrences

        result = am.get_occurrence_style(5)
        assert "error" in result


# ============================================================================
# BATCH 8: GET FACE STYLE
# ============================================================================


class TestGetFaceStyle:
    def test_success(self, asm_mgr):
        am, doc = asm_mgr
        occ = MagicMock()
        occ.GetFaceStyle2.return_value = "Aluminum"
        occurrences = MagicMock()
        occurrences.Count = 2
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        result = am.get_face_style(0)
        assert result["component_index"] == 0
        assert result["face_style"] == "Aluminum"
        # GetFaceStyle2(vbHonourPrefs as VT_BOOL)
        occ.GetFaceStyle2.assert_called_once_with(True)

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.get_face_style(0)
        assert "error" in result

    def test_invalid_index(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        doc.Occurrences = occurrences

        result = am.get_face_style(5)
        assert "error" in result


# ============================================================================
# GET OCCURRENCE BY ID
# ============================================================================


class TestGetOccurrence:
    def test_success(self, asm_mgr):
        am, doc = asm_mgr
        occ = MagicMock()
        occ.Name = "Part_1"
        occ.OccurrenceFileName = "C:/parts/part1.par"
        occ.GetTransform.return_value = [0.1, 0.2, 0.3, 0.0, 0.0, 0.0]
        occ.Visible = True

        occurrences = MagicMock()
        occurrences.GetOccurrence.return_value = occ
        doc.Occurrences = occurrences

        result = am.get_occurrence(42)
        assert result["internal_id"] == 42
        assert result["name"] == "Part_1"
        assert result["file_path"] == "C:/parts/part1.par"
        assert result["position"] == [0.1, 0.2, 0.3]
        occurrences.GetOccurrence.assert_called_once_with(42)

    def test_not_assembly(self, asm_mgr):
        am, doc = asm_mgr
        doc.Type = IG_PART_DOCUMENT

        result = am.get_occurrence(1)
        assert "error" in result
        assert "not an assembly" in result["error"]

    def test_com_error(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.GetOccurrence.side_effect = Exception("ID not found in occurrences")
        doc.Occurrences = occurrences

        result = am.get_occurrence(99999)
        assert "error" in result
        assert "ID not found" in result["error"]


# ============================================================================
# TRANSFORM UNITS
# ============================================================================


class TestTransformUnits:
    """GetTransform reports radians; this server's boundary is degrees.

    Every rotation setter (set_component_transform, put_transform_euler,
    occurrence_rotate) takes degrees, so a caller who read a rotation back
    and passed it straight to a setter was rotating by 1/57th of what they
    read. Each read path must hand back degrees.
    """

    QUARTER_TURN = [0.1, 0.2, 0.3, 0.0, 0.0, math.pi / 2]

    def _occ(self, transform):
        occ = MagicMock()
        occ.Name = "Part_1"
        occ.OccurrenceFileName = "C:/parts/part1.par"
        occ.GetTransform.return_value = transform
        occ.Visible = True
        return occ

    def test_list_components_reports_degrees(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        occurrences.Item.return_value = self._occ(self.QUARTER_TURN)
        doc.Occurrences = occurrences

        comp = am.list_components()["components"][0]
        assert comp["position"] == [0.1, 0.2, 0.3]
        assert comp["rotation_degrees"] == pytest.approx([0.0, 0.0, 90.0])

    def test_component_info_reports_degrees(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        occurrences.Item.return_value = self._occ(self.QUARTER_TURN)
        doc.Occurrences = occurrences

        info = am.get_component_info(0)
        assert info["rotation_degrees"] == pytest.approx([0.0, 0.0, 90.0])
        assert "rotation_rad" not in info

    def test_component_transform_reports_degrees(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.Count = 1
        occurrences.Item.return_value = self._occ(self.QUARTER_TURN)
        doc.Occurrences = occurrences

        result = am.get_component_transform(0)
        assert result["origin"] == [0.1, 0.2, 0.3]
        assert result["rotation_degrees"] == pytest.approx([0.0, 0.0, 90.0])
        assert "rotation_angles" not in result

    def test_get_occurrence_reports_degrees(self, asm_mgr):
        am, doc = asm_mgr
        occurrences = MagicMock()
        occurrences.GetOccurrence.return_value = self._occ(self.QUARTER_TURN)
        doc.Occurrences = occurrences

        info = am.get_occurrence(42)
        assert info["rotation_degrees"] == pytest.approx([0.0, 0.0, 90.0])

    def test_round_trip_through_a_setter(self, asm_mgr):
        """What a read hands back is what a setter accepts."""
        am, doc = asm_mgr
        occ = self._occ(self.QUARTER_TURN)
        occurrences = MagicMock()
        occurrences.Count = 1
        occurrences.Item.return_value = occ
        doc.Occurrences = occurrences

        rotation = am.get_component_transform(0)["rotation_degrees"]
        am.set_component_transform(0, 0.0, 0.0, 0.0, *rotation)

        # PutTransform takes radians: the degrees we read must arrive back as
        # the same radians GetTransform reported.
        assert occ.PutTransform.call_args.args[5] == pytest.approx(math.pi / 2)
