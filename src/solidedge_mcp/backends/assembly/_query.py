"""Query operations for assembly components."""

import contextlib
import math
import os
import re
import tempfile
from typing import Any

import pythoncom
from win32com.client import VARIANT

from solidedge_mcp.backends.errors import error_result

from ..comutil import describe_document_type
from ..constants import (
    InterferenceComparisonConstants,
    InterferenceReportConstants,
    InterferenceStatusConstants,
)
from ..logging import get_logger
from ._base import com_get

_logger = get_logger(__name__)

_INTERFERENCE_STATUS = {
    InterferenceStatusConstants.seInterferenceStatusNoInterference: "none",
    InterferenceStatusConstants.seInterferenceStatusConfirmedInterference: "confirmed",
    InterferenceStatusConstants.seInterferenceStatusProbableInterference: "probable",
    InterferenceStatusConstants.seInterferenceStatusConfirmedAndProbableInterference: (
        "confirmed_and_probable"
    ),
    InterferenceStatusConstants.seInterferenceStatusIncompleteAnalysis: "incomplete",
}

# "1 of 3" / "1 von 3": the first line of one interference block.
_BLOCK_HEADER = re.compile(r"^\s*(\d+)\s+\S+\s+(\d+)\s*$")
# "rahmen.par:1": an occurrence name not among the top-level ones (nested).
_OCCURRENCE_NAME = re.compile(r"^\S.*:\d+$")
# "Interference volume 1.808 mm^3": a number followed by a cubed unit.
_VOLUME = re.compile(r"([-+]?\d+(?:[.,]\d+)?)\s*([^\s\d]*\^3)")


def parse_interference_report(text: str, occurrence_names: list[str]) -> list[dict[str, Any]]:
    """Read the interference blocks of a CheckInterference report.

    The labels are in the UI language, so the parse relies on structure: a
    block starts with a line of two numbers around one word ("1 of 3"), lines
    equal to an occurrence name (or shaped like one, "name.par:1") are the
    parts, and lines with a cubed unit are volumes. Any other line in the
    block is kept in "notes".
    """
    known = {name for name in occurrence_names if name}
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            current = None
            continue
        if _BLOCK_HEADER.match(line):
            current = {"parts": [], "volumes": [], "volume_unit": None, "notes": []}
            blocks.append(current)
            continue
        if current is None:
            continue
        volume = _VOLUME.search(line)
        if line in known or (not volume and _OCCURRENCE_NAME.match(line)):
            current["parts"].append(line)
        elif volume:
            current["volumes"].append(float(volume.group(1).replace(",", ".")))
            current["volume_unit"] = volume.group(2)
        else:
            current["notes"].append(line)
    for block in blocks:
        block["total_volume"] = sum(block["volumes"])
    return blocks


class QueryMixin:
    """Mixin providing assembly query/interrogation methods."""

    @staticmethod
    def _transform_degrees(transform: Any) -> tuple[list[float], list[float]]:
        """Split an Occurrence.GetTransform() result into position + degrees.

        GetTransform reports its angles in radians, but meters and degrees are
        the unit at this server's boundary: a caller who read ``rotation`` back
        and passed it to set_component_orientation was rotating by 1/57th of
        what they read.
        """
        position = [transform[0], transform[1], transform[2]]
        rotation = [
            math.degrees(transform[3]),
            math.degrees(transform[4]),
            math.degrees(transform[5]),
        ]
        return position, rotation

    def list_components(self) -> dict[str, Any]:
        """
        List all components in the active assembly.

        Uses Occurrence.GetTransform() for position/rotation and
        OccurrenceFileName for file path. Positions are meters and
        rotations degrees, matching what the setters take.

        Returns:
            Dict with list of components and their properties
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences
            components = []

            for i in range(1, occurrences.Count + 1):
                occurrence = occurrences.Item(i)
                comp = {
                    "index": i - 1,
                    "name": com_get(occurrence, "Name", f"Component {i}"),
                }

                # Get file path
                try:
                    comp["file_path"] = occurrence.OccurrenceFileName
                except Exception:
                    comp["file_path"] = "Unknown"

                # Get transform (originX, originY, originZ, angleX, angleY, angleZ)
                try:
                    transform = occurrence.GetTransform()
                    comp["position"], comp["rotation_degrees"] = self._transform_degrees(transform)
                except Exception:
                    comp["position"] = [0.0, 0.0, 0.0]
                    comp["rotation_degrees"] = [0.0, 0.0, 0.0]

                # Visibility/suppression
                try:
                    comp["visible"] = occurrence.Visible
                except Exception:
                    comp["visible"] = True

                components.append(comp)

            return {"components": components, "count": len(components)}
        except Exception as e:
            return error_result(e)

    def get_component_info(self, component_index: int) -> dict[str, Any]:
        """
        Get detailed information about a specific component.

        Uses GetTransform for position/rotation and GetMatrix for the full 4x4
        matrix. Rotations are degrees, matching what the setters take.

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with component details
        """
        try:
            doc = self.doc_manager.get_active_document()
            occurrences = doc.Occurrences

            if component_index < 0 or component_index >= occurrences.Count:
                return {
                    "error": f"Invalid component index: "
                    f"{component_index}. "
                    f"Count: {occurrences.Count}"
                }

            occurrence = occurrences.Item(component_index + 1)

            info = {
                "index": component_index,
                "name": com_get(occurrence, "Name", "Unknown"),
            }

            # File path
            try:
                info["file_path"] = occurrence.OccurrenceFileName
            except Exception:
                info["file_path"] = "Unknown"

            # Transform (position + rotation)
            try:
                transform = occurrence.GetTransform()
                info["position"], info["rotation_degrees"] = self._transform_degrees(transform)
            except Exception:
                pass

            # Full 4x4 matrix
            with contextlib.suppress(Exception):
                info["matrix"] = self._get_occurrence_matrix(occurrence)

            # Visibility
            with contextlib.suppress(Exception):
                info["visible"] = occurrence.Visible

            # Occurrence document info
            try:
                occ_doc = occurrence.OccurrenceDocument
                info["document_name"] = occ_doc.Name
            except Exception:
                pass

            return info
        except Exception as e:
            return error_result(e)

    def get_component_transform(self, component_index: int) -> dict[str, Any]:
        """
        Get the full transformation matrix of a component.

        Returns the 4x4 homogeneous transformation matrix and decomposed
        origin (meters) + rotation (degrees).

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with matrix, origin, and rotation
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences

            if component_index < 0 or component_index >= occurrences.Count:
                return {
                    "error": f"Invalid component index: "
                    f"{component_index}. "
                    f"Count: {occurrences.Count}"
                }

            occurrence = occurrences.Item(component_index + 1)

            result = {
                "component_index": component_index,
                "name": occurrence.Name,
            }

            # Try GetTransform (origin + angles)
            try:
                transform = occurrence.GetTransform()
                result["origin"], result["rotation_degrees"] = self._transform_degrees(transform)
            except Exception:
                pass

            # Try GetMatrix (full 4x4)
            with contextlib.suppress(Exception):
                result["matrix"] = self._get_occurrence_matrix(occurrence)

            return result
        except Exception as e:
            return error_result(e)

    def get_occurrence_bounding_box(self, component_index: int) -> dict[str, Any]:
        """
        Get the bounding box of a specific component (occurrence) in the assembly.

        Uses Occurrence.GetRangeBox() which returns min/max 3D points.

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with min/max coordinates
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences

            if component_index < 0 or component_index >= occurrences.Count:
                return {
                    "error": f"Invalid component index: "
                    f"{component_index}. "
                    f"Count: {occurrences.Count}"
                }

            occurrence = occurrences.Item(component_index + 1)

            # GetRangeBox(MinRangePoint, MaxRangePoint), both [in,out]
            # SAFEARRAY(VT_R8). pywin32 fills a copy and hands the points back
            # in the return value; the buffers we pass are never written to.
            # Reading them back gave every component a zero-sized box.
            min_point, max_point = occurrence.GetRangeBox([0.0] * 3, [0.0] * 3)

            return {
                "component_index": component_index,
                "min": [min_point[0], min_point[1], min_point[2]],
                "max": [max_point[0], max_point[1], max_point[2]],
                "size": [
                    max_point[0] - min_point[0],
                    max_point[1] - min_point[1],
                    max_point[2] - min_point[2],
                ],
            }
        except Exception as e:
            return error_result(e)

    def is_subassembly(self, component_index: int) -> dict[str, Any]:
        """
        Check if a component is a subassembly (vs a part).

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with is_subassembly boolean
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences
            if component_index < 0 or component_index >= occurrences.Count:
                return {
                    "error": f"Invalid component index: "
                    f"{component_index}. "
                    f"Count: {occurrences.Count}"
                }

            occurrence = occurrences.Item(component_index + 1)

            result = {"component_index": component_index}

            try:
                result["is_subassembly"] = occurrence.Subassembly
            except Exception:
                # Fallback: check if it has SubOccurrences
                try:
                    sub_occs = occurrence.SubOccurrences
                    result["is_subassembly"] = com_get(sub_occs, "Count", 0) > 0
                except Exception:
                    result["is_subassembly"] = False

            with contextlib.suppress(Exception):
                result["name"] = occurrence.Name

            return result
        except Exception as e:
            return error_result(e)

    def get_component_display_name(self, component_index: int) -> dict[str, Any]:
        """
        Get the display name of a component.

        The display name is the user-visible label in the assembly tree,
        which may differ from the internal Name or OccurrenceFileName.

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with display_name and other name info
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences
            if component_index < 0 or component_index >= occurrences.Count:
                return {
                    "error": f"Invalid component index: "
                    f"{component_index}. "
                    f"Count: {occurrences.Count}"
                }

            occurrence = occurrences.Item(component_index + 1)

            result: dict[str, Any] = {"component_index": component_index}

            # Occurrence has no DisplayName. Name already reads as
            # "part.par:1", which is the display name Solid Edge shows.
            with contextlib.suppress(Exception):
                result["display_name"] = occurrence.Name

            with contextlib.suppress(Exception):
                result["name"] = occurrence.Name

            with contextlib.suppress(Exception):
                result["file_name"] = occurrence.OccurrenceFileName

            return result
        except Exception as e:
            return error_result(e)

    def get_occurrence_document(self, component_index: int) -> dict[str, Any]:
        """
        Get document info for a component's source file.

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with document name, path, and type
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences
            if component_index < 0 or component_index >= occurrences.Count:
                return {
                    "error": f"Invalid component index: "
                    f"{component_index}. "
                    f"Count: {occurrences.Count}"
                }

            occurrence = occurrences.Item(component_index + 1)

            result: dict[str, Any] = {"component_index": component_index}

            try:
                occ_doc = occurrence.OccurrenceDocument
                with contextlib.suppress(Exception):
                    result["document_name"] = occ_doc.Name
                with contextlib.suppress(Exception):
                    result["full_name"] = occ_doc.FullName
                with contextlib.suppress(Exception):
                    result.update(describe_document_type(occ_doc.Type))
                with contextlib.suppress(Exception):
                    result["read_only"] = occ_doc.ReadOnly
            except Exception:
                result["error_note"] = "Could not access OccurrenceDocument"

            with contextlib.suppress(Exception):
                result["file_name"] = occurrence.OccurrenceFileName

            return result
        except Exception as e:
            return error_result(e)

    def get_sub_occurrences(self, component_index: int) -> dict[str, Any]:
        """
        Get sub-occurrences (children) of a component.

        For subassemblies, this returns the list of nested components.
        For parts, this returns an empty list.

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with list of sub-occurrence names and count
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences
            if component_index < 0 or component_index >= occurrences.Count:
                return {
                    "error": f"Invalid component index: "
                    f"{component_index}. "
                    f"Count: {occurrences.Count}"
                }

            occurrence = occurrences.Item(component_index + 1)

            children = []
            try:
                sub_occs = occurrence.SubOccurrences
                if sub_occs and com_get(sub_occs, "Count", 0):
                    for j in range(1, sub_occs.Count + 1):
                        try:
                            child = sub_occs.Item(j)
                            child_info: dict[str, Any] = {"index": j - 1}
                            try:
                                child_info["name"] = child.Name
                            except Exception:
                                child_info["name"] = f"SubOcc_{j}"
                            # A SubOccurrence names its file
                            # SubOccurrenceFileName; OccurrenceFileName is on
                            # Occurrence, so this key was always missing.
                            with contextlib.suppress(Exception):
                                child_info["file"] = child.SubOccurrenceFileName
                            children.append(child_info)
                        except Exception:
                            children.append({"index": j - 1, "name": f"SubOcc_{j}"})
            except Exception:
                pass

            return {
                "component_index": component_index,
                "sub_occurrences": children,
                "count": len(children),
            }
        except Exception as e:
            return error_result(e)

    def get_structured_bom(self) -> dict[str, Any]:
        """
        Get a hierarchical Bill of Materials with subassembly structure.

        Unlike get_bom() which returns a flat list, this preserves the
        parent-child hierarchy of subassemblies.

        Returns:
            Dict with structured BOM tree
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences

            def build_bom_item(occ: Any, depth: int = 0) -> dict[str, Any]:
                item = {}
                try:
                    item["name"] = occ.Name
                except Exception:
                    item["name"] = "Unknown"

                try:
                    item["file"] = occ.OccurrenceFileName
                except Exception:
                    item["file"] = "Unknown"

                with contextlib.suppress(Exception):
                    item["visible"] = occ.Visible

                try:
                    item["suppressed"] = occ.IsSuppressed
                except Exception:
                    item["suppressed"] = False

                # Check for sub-occurrences (subassembly)
                children = []
                try:
                    sub_occs = occ.SubOccurrences
                    if sub_occs and com_get(sub_occs, "Count", 0) > 0:
                        item["type"] = "assembly"
                        for j in range(1, sub_occs.Count + 1):
                            try:
                                children.append(build_bom_item(sub_occs.Item(j), depth + 1))
                            except Exception:
                                children.append({"name": f"SubItem_{j}", "error": "unreadable"})
                    else:
                        item["type"] = "part"
                except Exception:
                    item["type"] = "part"

                if children:
                    item["children"] = children
                    item["child_count"] = len(children)

                return item

            bom = []
            for i in range(1, occurrences.Count + 1):
                try:
                    bom.append(build_bom_item(occurrences.Item(i)))
                except Exception:
                    bom.append({"name": f"Component_{i}", "error": "unreadable"})

            return {
                "bom": bom,
                "top_level_count": len(bom),
                "document": com_get(doc, "Name", "Unknown"),
            }
        except Exception as e:
            return error_result(e)

    def get_occurrence_bodies(self, component_index: int) -> dict[str, Any]:
        """
        Get body information from a specific component occurrence.

        Reads occurrence.Bodies property to enumerate solid bodies.

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with body count and body info
        """
        try:
            doc = self.doc_manager.get_active_document()
            occurrences, occurrence, err = self._validate_occurrence_index(doc, component_index)
            if err:
                return err

            # Occurrence.Bodies does not exist, so this listed nothing for
            # every component. Body is a single get-only property, and
            # GetSimplifiedBodies reports the rest.
            bodies_info = []
            candidates = []
            single = com_get(occurrence, "Body")
            if single is not None:
                candidates.append(single)
            with contextlib.suppress(Exception):
                count, simplified = occurrence.GetSimplifiedBodies()
                if simplified:
                    candidates.extend(list(simplified)[: int(count)])

            for index, body in enumerate(candidates):
                body_info: dict[str, Any] = {"index": index}
                with contextlib.suppress(Exception):
                    body_info["name"] = body.Name
                with contextlib.suppress(Exception):
                    body_info["volume"] = body.Volume
                with contextlib.suppress(Exception):
                    body_info["is_solid"] = bool(body.IsSolid)
                bodies_info.append(body_info)

            return {
                "component_index": component_index,
                "body_count": len(bodies_info),
                "bodies": bodies_info,
            }
        except Exception as e:
            return error_result(e)

    def get_occurrence_style(self, component_index: int) -> dict[str, Any]:
        """
        Get the style (appearance) of a component occurrence.

        Reads occurrence.Style property.

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with style info
        """
        try:
            doc = self.doc_manager.get_active_document()
            occurrences, occurrence, err = self._validate_occurrence_index(doc, component_index)
            if err:
                return err

            result: dict[str, Any] = {"component_index": component_index}

            try:
                style = occurrence.Style
                result["style"] = str(style) if style is not None else None
            except Exception:
                result["style"] = None
                result["style_note"] = "Style property not available on this occurrence"

            return result
        except Exception as e:
            return error_result(e)

    def get_face_style(self, component_index: int) -> dict[str, Any]:
        """
        Get the face style of a component occurrence.

        Reads occurrence.GetFaceStyle2() for face style information.

        Args:
            component_index: 0-based index of the component

        Returns:
            Dict with face style info
        """
        try:
            doc = self.doc_manager.get_active_document()
            occurrences, occurrence, err = self._validate_occurrence_index(doc, component_index)
            if err:
                return err

            result: dict[str, Any] = {"component_index": component_index}

            try:
                # GetFaceStyle2(vbHonourPrefs as VT_BOOL)
                face_style = occurrence.GetFaceStyle2(True)
                result["face_style"] = str(face_style) if face_style is not None else None
            except Exception:
                result["face_style"] = None
                result["face_style_note"] = "GetFaceStyle2 not available on this occurrence"

            return result
        except Exception as e:
            return error_result(e)

    def get_occurrence(self, internal_id: int) -> dict[str, Any]:
        """
        Get an occurrence by its internal ID.

        Uses Occurrences.GetOccurrence(ID) to retrieve a specific occurrence
        by its internal ID (not by index). This is useful when you know the
        internal identifier assigned by Solid Edge.

        Args:
            internal_id: Internal ID of the occurrence (integer)

        Returns:
            Dict with occurrence info (name, file path, transform, etc.)
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences
            occurrence = occurrences.GetOccurrence(internal_id)

            if occurrence is None:
                return {"error": f"No occurrence found with ID: {internal_id}"}

            info: dict[str, Any] = {"internal_id": internal_id}

            # Name
            try:
                info["name"] = occurrence.Name
            except Exception:
                info["name"] = "Unknown"

            # File path
            try:
                info["file_path"] = occurrence.OccurrenceFileName
            except Exception:
                info["file_path"] = "Unknown"

            # Transform (position + rotation)
            try:
                transform = occurrence.GetTransform()
                info["position"], info["rotation_degrees"] = self._transform_degrees(transform)
            except Exception:
                pass

            # Full 4x4 matrix
            with contextlib.suppress(Exception):
                info["matrix"] = self._get_occurrence_matrix(occurrence)

            # Visibility
            with contextlib.suppress(Exception):
                info["visible"] = occurrence.Visible

            # Occurrence document info
            try:
                occ_doc = occurrence.OccurrenceDocument
                info["document_name"] = occ_doc.Name
            except Exception:
                pass

            return info
        except Exception as e:
            return error_result(e)

    def check_interference(self, component_index: int | None = None) -> dict[str, Any]:
        """
        Run interference check on the active assembly.

        If component_index is provided, checks that component against all others.
        If not provided, checks all components against each other.

        Args:
            component_index: Optional 0-based index of a specific component to check

        Returns:
            Dict with interference status and details
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences
            count = occurrences.Count

            if count < 2:
                return {
                    "status": "no_interference",
                    "message": "Need at least 2 components for interference check",
                }

            if component_index is not None and (component_index < 0 or component_index >= count):
                return {"error": f"Invalid component index: {component_index}"}

            names = [str(com_get(occurrences.Item(i), "Name", "")) for i in range(1, count + 1)]
            if component_index is None:
                set1 = [occurrences.Item(i) for i in range(1, count + 1)]
                comparison = InterferenceComparisonConstants.seInterferenceComparisonSet1vsItself
            else:
                set1 = [occurrences.Item(component_index + 1)]
                comparison = InterferenceComparisonConstants.seInterferenceComparisonSet1vsAllOther

            # Solid Edge must not be handed a path that exists (it prompts),
            # so the report goes to a fresh name in a new temp directory.
            report_path = os.path.join(tempfile.mkdtemp(prefix="se_interference_"), "report.txt")
            report_type = (
                InterferenceReportConstants.seInterferenceReportPartNames
                | InterferenceReportConstants.seInterferenceReportInterferenceVolume
            )

            # Called through IDispatch.Invoke, verified on Solid Edge 2026. The
            # type-library wrapper marshals Set1 as a VARIANT array, which
            # answers DISP_E_TYPEMISMATCH; it has to be VT_ARRAY | VT_DISPATCH.
            # Passing the [out] NumInterferences/InterferingParts* parameters
            # answers E_INVALIDARG, so they are omitted and the report is read
            # instead. An empty ReportFilename or ReportType 0 is E_INVALIDARG.
            ole = doc._oleobj_
            dispid = ole.GetIDsOfNames(0, "CheckInterference")
            status = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            ole.Invoke(
                dispid,
                0,
                pythoncom.DISPATCH_METHOD,
                True,
                len(set1),
                VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, set1),
                status,
                comparison,
                pythoncom.ArgNotFound,  # NumElementsSet2
                pythoncom.ArgNotFound,  # Set2
                False,  # AddInterferenceAsOccurrence
                report_path,
                report_type,
            )

            report_text = None
            if os.path.exists(report_path):
                with open(report_path, encoding="utf-8-sig", errors="replace") as f:
                    report_text = f.read()
            interferences = parse_interference_report(report_text or "", names)

            status_code = status.value
            return {
                "status": "interference" if interferences else "no_interference",
                "interference_count": len(interferences),
                "interferences": interferences,
                "check_status": _INTERFERENCE_STATUS.get(status_code, "unknown"),
                "check_status_code": status_code,
                "component_checked": component_index,
                "report_path": report_path if report_text is not None else None,
                "report": report_text,
            }

        except Exception as e:
            return error_result(e)

    def get_bom(self) -> dict[str, Any]:
        """
        Get Bill of Materials from the active assembly.

        Recursively traverses all occurrences, deduplicates by file path,
        and returns a flat BOM with quantities.

        Returns:
            Dict with BOM items (file, name, quantity)
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences
            bom_counts: dict[str, dict[str, Any]] = {}

            for i in range(1, occurrences.Count + 1):
                occurrence = occurrences.Item(i)

                # Skip items excluded from BOM
                try:
                    if not com_get(occurrence, "IncludeInBom", True):
                        continue
                except Exception:
                    pass

                # Skip pattern items (counted as part of pattern source)
                try:
                    if com_get(occurrence, "IsPatternItem", False):
                        continue
                except Exception:
                    pass

                # Get file path as key
                try:
                    file_path = occurrence.OccurrenceFileName
                except Exception:
                    file_path = f"Unknown_{i}"

                name = com_get(occurrence, "Name", os.path.basename(file_path))

                if file_path in bom_counts:
                    bom_counts[file_path]["quantity"] += 1
                else:
                    bom_counts[file_path] = {"name": name, "file_path": file_path, "quantity": 1}

            bom_items = list(bom_counts.values())

            return {
                "total_occurrences": occurrences.Count,
                "unique_parts": len(bom_items),
                "bom": bom_items,
            }
        except Exception as e:
            return error_result(e)

    def get_assembly_relations(self) -> dict[str, Any]:
        """
        Get all assembly relations (constraints) in the active assembly.

        Iterates the Relations3d collection to report constraint types,
        status, and connected occurrences.

        Returns:
            Dict with list of relations and their properties
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            relations = doc.Relations3d
            relation_list = []

            # Relation type constants
            type_names = {
                0: "Ground",
                1: "Axial",
                2: "Planar",
                3: "Connect",
                4: "Angle",
                5: "Tangent",
                6: "Cam",
                7: "Gear",
                8: "ParallelAxis",
                9: "Center",
            }

            for i in range(1, relations.Count + 1):
                try:
                    rel = relations.Item(i)
                    rel_info: dict[str, Any] = {"index": i - 1}

                    try:
                        rel_info["type"] = rel.Type
                        rel_info["type_name"] = type_names.get(rel.Type, f"Unknown({rel.Type})")
                    except Exception:
                        pass

                    with contextlib.suppress(Exception):
                        rel_info["status"] = rel.Status

                    with contextlib.suppress(Exception):
                        rel_info["suppressed"] = rel.Suppressed

                    with contextlib.suppress(Exception):
                        rel_info["name"] = rel.Name

                    relation_list.append(rel_info)
                except Exception:
                    relation_list.append({"index": i - 1})

            return {"relations": relation_list, "count": len(relation_list)}
        except Exception as e:
            return error_result(e)

    def get_document_tree(self) -> dict[str, Any]:
        """
        Get the hierarchical document tree of the active assembly.

        Recursively traverses occurrences and sub-occurrences to build
        a nested tree structure showing the full assembly hierarchy.

        Returns:
            Dict with nested tree of components
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            def traverse_occurrence(occ: Any, depth: int = 0) -> dict[str, Any]:
                """Recursively build tree from an occurrence."""
                node = {}

                try:
                    node["name"] = occ.Name
                except Exception:
                    node["name"] = "Unknown"

                try:
                    node["file"] = occ.OccurrenceFileName
                except Exception:
                    node["file"] = "Unknown"

                with contextlib.suppress(Exception):
                    node["visible"] = occ.Visible

                with contextlib.suppress(Exception):
                    node["suppressed"] = com_get(occ, "IsSuppressed", False)

                # Recurse into sub-occurrences
                children = []
                try:
                    sub_occs = occ.SubOccurrences
                    if sub_occs and com_get(sub_occs, "Count", 0):
                        for j in range(1, sub_occs.Count + 1):
                            try:
                                child = sub_occs.Item(j)
                                children.append(traverse_occurrence(child, depth + 1))
                            except Exception:
                                children.append({"name": f"SubOcc_{j}", "error": "could not read"})
                except Exception:
                    pass

                if children:
                    node["children"] = children

                return node

            occurrences = doc.Occurrences
            tree = []

            for i in range(1, occurrences.Count + 1):
                try:
                    occ = occurrences.Item(i)
                    tree.append(traverse_occurrence(occ))
                except Exception:
                    tree.append({"name": f"Occurrence_{i}", "error": "could not read"})

            return {
                "tree": tree,
                "top_level_count": len(tree),
                "document": com_get(doc, "Name", "Unknown"),
            }
        except Exception as e:
            return error_result(e)

    def get_occurrence_count(self) -> dict[str, Any]:
        """
        Get the count of top-level occurrences in the assembly.

        Returns:
            Dict with occurrence count
        """
        try:
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            return {"count": doc.Occurrences.Count}
        except Exception as e:
            return error_result(e)
