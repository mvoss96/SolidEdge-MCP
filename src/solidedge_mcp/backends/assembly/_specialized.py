"""Specialized assembly subsystem operations (virtual components, tubes, frames, wiring)."""

import contextlib
import os
from typing import Any

import pythoncom
from win32com.client import VARIANT

from solidedge_mcp.backends.errors import error_result

from ..comutil import com_get
from ..constants import (
    KeypointEndConditionConstants,
    KeyPointTypeConstants,
    PointTypeConstants,
)
from ..dialogs import dismiss_informational_dialog
from ..features._base import verifies_collection_growth
from ..logging import get_logger

_logger = get_logger(__name__)


class SpecializedMixin:
    """Mixin providing specialized assembly subsystem methods."""

    # -- Virtual Components --------------------------------------------------

    def _active_harness(self, doc: Any) -> tuple[Any, dict[str, Any] | None]:
        """The assembly's harness, creating one when there is none.

        Wires, cables, splices and bundles hang off a Harness, which hangs off
        AssemblyDocument.Harnesses. Reading them straight from the document
        raised every time.
        """
        harnesses = com_get(doc, "Harnesses")
        if harnesses is None:
            return None, {
                "error": (
                    "This assembly has no Harnesses collection, so wiring cannot "
                    "be added. Harness work needs Solid Edge Wire Harness Design."
                )
            }
        try:
            if int(com_get(harnesses, "Count", 0) or 0):
                return harnesses.Item(1), None
            return harnesses.Add(), None
        except Exception as exc:
            return None, error_result(exc, context="Could not open a wire harness")

    def add_virtual_component(
        self,
        name: str,
        component_type: str = "Part",
    ) -> dict[str, Any]:
        """
        Add a virtual component to the assembly.

        Virtual components are placeholders for parts that don't yet have
        geometry files. Uses VirtualComponentOccurrences.Add.

        Args:
            name: Name for the virtual component
            component_type: 'Part' (3), 'Assembly' (2), 'Sheetmetal' (4),
                or 'Unknown' (1)

        Returns:
            Dict with status and virtual component info
        """
        try:
            _logger.info(f"Adding virtual component: name={name}, type={component_type}")
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            type_map = {
                "Unknown": 1,
                "Assembly": 2,
                "Part": 3,
                "Sheetmetal": 4,
            }
            vc_type = type_map.get(component_type, 3)

            vc_occs = doc.VirtualComponentOccurrences
            vc_occ = vc_occs.Add(name, vc_type)

            result: dict[str, Any] = {
                "status": "created",
                "name": name,
                "component_type": component_type,
            }

            with contextlib.suppress(Exception):
                result["vc_name"] = vc_occ.Name

            return result
        except Exception as e:
            _logger.error(f"Failed to add virtual component: {e}")
            return error_result(e)

    def add_virtual_component_predefined(
        self,
        filename: str,
    ) -> dict[str, Any]:
        """
        Add a pre-defined virtual component from a file.

        Uses VirtualComponentOccurrences.AddAsPreDefined.

        Args:
            filename: Path to the virtual component file

        Returns:
            Dict with status and virtual component info
        """
        try:
            _logger.info(f"Adding predefined virtual component: {filename}")
            if not os.path.exists(filename):
                return {"error": f"File not found: {filename}"}

            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            vc_occs = doc.VirtualComponentOccurrences
            vc_occ = vc_occs.AddAsPreDefined(filename)

            result: dict[str, Any] = {
                "status": "created",
                "filename": filename,
            }

            with contextlib.suppress(Exception):
                result["vc_name"] = vc_occ.Name

            return result
        except Exception as e:
            _logger.error(f"Failed to add predefined virtual component: {e}")
            return error_result(e)

    def add_virtual_component_bidm(
        self,
        doc_number: str,
        revision_id: str,
        component_type: str = "Part",
    ) -> dict[str, Any]:
        """
        Add a virtual component using BIDM (document number + revision).

        Uses VirtualComponentOccurrences.AddBIDM.

        Args:
            doc_number: Document number string
            revision_id: Revision ID string
            component_type: 'Part' (3), 'Assembly' (2), 'Sheetmetal' (4),
                or 'Unknown' (1)

        Returns:
            Dict with status and virtual component info
        """
        try:
            _logger.info(f"Adding virtual component via BIDM: doc={doc_number}, rev={revision_id}")
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            type_map = {
                "Unknown": 1,
                "Assembly": 2,
                "Part": 3,
                "Sheetmetal": 4,
            }
            vc_type = type_map.get(component_type, 3)

            vc_occs = doc.VirtualComponentOccurrences
            vc_occ = vc_occs.AddBIDM(doc_number, revision_id, vc_type)

            result: dict[str, Any] = {
                "status": "created",
                "doc_number": doc_number,
                "revision_id": revision_id,
                "component_type": component_type,
            }

            with contextlib.suppress(Exception):
                result["vc_name"] = vc_occ.Name

            return result
        except Exception as e:
            _logger.error(f"Failed to add virtual component via BIDM: {e}")
            return error_result(e)

    # -- Tube Operations -----------------------------------------------------

    def get_tube(self, component_index: int) -> dict[str, Any]:
        """
        Get tube information from a tube occurrence.

        Uses Occurrence.GetTube() to retrieve tube properties.

        Args:
            component_index: 0-based index of the tube component

        Returns:
            Dict with tube properties (outer diameter, wall thickness, etc.)
        """
        try:
            _logger.info(f"Getting tube info: component_index={component_index}")
            doc = self.doc_manager.get_active_document()
            occurrences, occurrence, err = self._validate_occurrence_index(doc, component_index)
            if err:
                return err

            tube = occurrence.GetTube()
            if tube is None:
                return {
                    "error": f"Component at index {component_index} "
                    "is not a tube or has no tube data"
                }

            result: dict[str, Any] = {
                "component_index": component_index,
                "is_tube": True,
            }

            with contextlib.suppress(Exception):
                result["outer_diameter"] = tube.OuterDiameter
            with contextlib.suppress(Exception):
                result["wall_thickness"] = tube.WallThickness
            with contextlib.suppress(Exception):
                result["bend_radius"] = tube.BendRadius
            with contextlib.suppress(Exception):
                result["material"] = tube.Material
            with contextlib.suppress(Exception):
                result["is_solid"] = tube.IsSolid
            with contextlib.suppress(Exception):
                result["length"] = tube.Length

            return result
        except Exception as e:
            _logger.error(f"Failed to get tube info: {e}")
            return error_result(e)

    def add_tube(
        self,
        segment_indices: list[int],
        part_filename: str,
        outer_diameter: float = 0.0,
        wall_thickness: float = 0.0,
        bend_radius: float = 0.0,
        is_solid: bool = False,
    ) -> dict[str, Any]:
        """
        Add a tube occurrence to the assembly.

        Uses Occurrences.AddTube with VARIANT-wrapped segment array.

        Args:
            segment_indices: 0-based indices of occurrences that define
                tube path segments
            part_filename: Path to the tube part file template
            outer_diameter: Outer diameter in meters (0 = use template)
            wall_thickness: Wall thickness in meters (0 = use template)
            bend_radius: Bend radius in meters (0 = use template)
            is_solid: True for solid tube, False for hollow

        Returns:
            Dict with status and tube occurrence info
        """
        try:
            _logger.info(f"Adding tube: part={part_filename}, segments={len(segment_indices)}")
            if not os.path.exists(part_filename):
                return {"error": f"File not found: {part_filename}"}

            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences

            # Resolve segment indices to occurrence objects
            segments = []
            for idx in segment_indices:
                if idx < 0 or idx >= occurrences.Count:
                    return {"error": f"Invalid segment index: {idx}. Count: {occurrences.Count}"}
                segments.append(occurrences.Item(idx + 1))

            v_segments = segments

            occ = occurrences.AddTube(
                v_segments,
                part_filename,
                None,  # TemplateFileName (optional)
                is_solid,  # IsSolid
                None,  # Material
                bend_radius if bend_radius > 0 else None,
                outer_diameter if outer_diameter > 0 else None,
                None,  # MinimumFlatLength
                wall_thickness if wall_thickness > 0 else None,
            )

            result: dict[str, Any] = {
                "status": "created",
                "type": "tube",
                "part_filename": part_filename,
                "num_segments": len(segments),
            }

            with contextlib.suppress(Exception):
                result["name"] = occ.Name

            return result
        except Exception as e:
            _logger.error(f"Failed to add tube: {e}")
            return error_result(e)

    # -- Structural Frames ---------------------------------------------------

    @verifies_collection_growth("StructuralFrames")
    def add_structural_frame(
        self,
        part_filename: str,
        path_indices: list[int],
    ) -> dict[str, Any]:
        """
        Run a structural frame along 3D sketch lines.

        ``StructuralFrames.Add(PartFileName, NumPaths, Path, GlobalEndConditions,
        GlobalEndConditionValue, AutoPosition)`` takes the Line3D objects drawn
        by ``draw_line_3d`` as its Path; verified on Solid Edge 2026 along one
        and two lines (StructuralFrames.Count grows, an occurrence appears).
        The first frame in a session raises an informational "Segments group
        ... 3D Draw" dialog that blocks the call until OK is clicked, so that
        one dialog is dismissed while the call runs; see backends/dialogs.py.

        Args:
            part_filename: The frame cross-section part file (must exist).
            path_indices: 0-based indices of the 3D lines from draw_3d_line.

        Returns:
            Dict with status, frame count, and whether the dialog was dismissed.
        """
        try:
            doc = self.doc_manager.get_active_document()
            err = self._require_assembly(doc)
            if err:
                return err
            if not os.path.exists(part_filename):
                return {"error": f"Frame part does not exist: {part_filename}"}
            lines = list(getattr(self.sketch_manager, "lines_3d", None) or [])
            if not path_indices:
                return {
                    "error": (
                        "path_indices names the 3D lines the frame runs along "
                        "(draw_3d_line, 0-based); none were given."
                    )
                }
            bad = [i for i in path_indices if i < 0 or i >= len(lines)]
            if bad:
                return {
                    "error": (
                        f"Invalid path index {bad[0]}: {len(lines)} 3D line(s) drawn in "
                        "this document with draw_3d_line."
                    )
                }
            path = [lines[i] for i in path_indices]
            empty = VARIANT(pythoncom.VT_EMPTY, None)
            with dismiss_informational_dialog("The Segments group of commands") as dialog:
                doc.StructuralFrames.Add(part_filename, len(path), path, empty, empty, empty)
            return {
                "status": "created",
                "type": "structural_frame",
                "part_filename": part_filename,
                "path_indices": path_indices,
                "frames": com_get(doc.StructuralFrames, "Count"),
                "dialog_dismissed": dialog.dismissed,
            }
        except Exception as e:
            return error_result(e)

    @verifies_collection_growth("StructuralFrames")
    def add_structural_frame_by_orientation(
        self,
        part_filename: str,
        coord_system_name: str,
        path_indices: list[int],
    ) -> dict[str, Any]:
        """
        Structural frames cannot be created through COM automation here.

        Like ``add_structural_frame``, along 3D sketch lines from ``draw_line_3d``.

        Args:
            part_filename: Unused.
            coord_system_name: Unused.
            path_indices: Unused.

        Returns:
            Dict with an ``unsupported`` error.
        """
        try:
            doc = self.doc_manager.get_active_document()
            err = self._require_assembly(doc)
            if err:
                return err
            if not os.path.exists(part_filename):
                return {"error": f"Frame part does not exist: {part_filename}"}
            lines = list(getattr(self.sketch_manager, "lines_3d", None) or [])
            if not path_indices:
                return {
                    "error": (
                        "path_indices names the 3D lines the frame runs along "
                        "(draw_3d_line, 0-based); none were given."
                    )
                }
            bad = [i for i in path_indices if i < 0 or i >= len(lines)]
            if bad:
                return {
                    "error": (
                        f"Invalid path index {bad[0]}: {len(lines)} 3D line(s) drawn in "
                        "this document with draw_3d_line."
                    )
                }
            path = [lines[i] for i in path_indices]
            # StructuralFrames.AddByOrientation(PartFileName, CoOrdinateSystemName,
            #   NumPaths, Path, PreferredOrientationPlane, GlobalEndConditions,
            #   GlobalEndConditionValue, AutoPosition). Verified on Solid Edge 2026
            # with an empty coordinate-system name; the same informational dialog
            # as Add is dismissed while it runs.
            empty = VARIANT(pythoncom.VT_EMPTY, None)
            with dismiss_informational_dialog("The Segments group of commands") as dialog:
                doc.StructuralFrames.AddByOrientation(
                    part_filename, coord_system_name, len(path), path, empty, empty, empty, empty
                )
            return {
                "status": "created",
                "type": "structural_frame_by_orientation",
                "part_filename": part_filename,
                "coord_system_name": coord_system_name,
                "path_indices": path_indices,
                "frames": com_get(doc.StructuralFrames, "Count"),
                "dialog_dismissed": dialog.dismissed,
            }
        except Exception as e:
            return error_result(e)

    def add_splice(
        self,
        x: float,
        y: float,
        z: float,
        conductor_indices: list[int],
        description: str = "",
    ) -> dict[str, Any]:
        """
        Add a splice to the assembly wiring harness.

        Uses Splices.Add with VARIANT-wrapped conductor array.

        Args:
            x: Splice X position in meters
            y: Splice Y position in meters
            z: Splice Z position in meters
            conductor_indices: 0-based indices of conductor occurrences
            description: Description text for the splice

        Returns:
            Dict with status and splice info
        """
        try:
            _logger.info(f"Adding splice at ({x},{y},{z}) with {len(conductor_indices)} conductors")
            doc = self.doc_manager.get_active_document()

            err = self._require_assembly(doc)
            if err:
                return err

            occurrences = doc.Occurrences

            conductors = []
            for idx in conductor_indices:
                if idx < 0 or idx >= occurrences.Count:
                    return {"error": f"Invalid conductor index: {idx}. Count: {occurrences.Count}"}
                conductors.append(occurrences.Item(idx + 1))

            v_conductors = conductors

            # Splices belongs to a Harness, not to the document; reading it
            # off the document always raised. A harness is created on
            # demand so the first wire in an assembly has somewhere to go.
            harness, err = self._active_harness(doc)
            if err:
                return err
            splices = harness.Splices
            splice = splices.Add(
                x,
                y,
                z,
                len(conductors),
                v_conductors,
                description,
            )

            result: dict[str, Any] = {
                "status": "created",
                "type": "splice",
                "position": [x, y, z],
                "num_conductors": len(conductors),
                "description": description,
            }

            with contextlib.suppress(Exception):
                result["name"] = splice.Name

            return result
        except Exception as e:
            _logger.error(f"Failed to add splice: {e}")
            return error_result(e)

    # -- Wires, cables and bundles -------------------------------------------

    @staticmethod
    def _harness_paths(
        doc: Any, path_indices: list[int], path_points: list[list[float]] | None, what: str
    ) -> tuple[list[Any], dict[str, Any] | None]:
        """Harness paths for a conductor: existing ones by index, or one through points.

        Wires.Add, Cables.Add and Bundles.Add route along AssemblyDocument.Paths
        entries; occurrences and 3D sketch lines answer E_FAIL (Solid Edge
        2026). A path through space points is made with Paths.Add, which
        answers E_INVALIDARG unless EndpointEndType is passed as well.
        """
        harness_paths = doc.Paths
        if path_points:
            if path_indices:
                return [], {"error": "Pass path_points or path_indices, not both."}
            if len(path_points) < 2 or any(len(pt) != 3 for pt in path_points):
                return [], {"error": "path_points needs two or more [x, y, z] points."}
            n = len(path_points)
            natural = KeypointEndConditionConstants.seKeypointEndConditionNatural
            path = harness_paths.Add(
                n,
                [PointTypeConstants.igSpacePoint] * n,
                [None] * n,
                [KeyPointTypeConstants.igKeyPointPointOnly] * n,
                [float(c) for pt in path_points for c in pt],
                natural,
                natural,
            )
            return [path], None
        paths = []
        for idx in path_indices:
            if idx < 0 or idx >= harness_paths.Count:
                return [], {
                    "error": f"Invalid path index: {idx}. "
                    f"The assembly has {harness_paths.Count} harness paths."
                }
            paths.append(harness_paths.Item(idx + 1))
        if not paths:
            return [], {"error": f"A {what} needs path_points or path_indices."}
        return paths, None

    @staticmethod
    def _harness_items(collection: Any, indices: list[int], what: str) -> tuple[list[Any], Any]:
        """Items of a harness collection by 0-based index, or an error dict."""
        items = []
        for idx in indices:
            if idx < 0 or idx >= collection.Count:
                return [], {
                    "error": f"Invalid {what} index: {idx}. The harness has {collection.Count}."
                }
            items.append(collection.Item(idx + 1))
        return items, None

    def add_wire(
        self,
        path_indices: list[int],
        path_directions: list[bool],
        description: str = "",
        path_points: list[list[float]] | None = None,
    ) -> dict[str, Any]:
        """Add a wire to the assembly's harness along harness paths.

        Wires.Add(NumberOfPaths, PathArray, PathDirectionArray,
        ConductorDescription). path_indices are 0-based indices into
        AssemblyDocument.Paths; path_points (x, y, z in meters, two or more)
        makes a path through those points first.
        """
        try:
            doc = self.doc_manager.get_active_document()
            err = self._require_assembly(doc)
            if err:
                return err
            paths, err = self._harness_paths(doc, path_indices, path_points, "wire")
            if err:
                return err
            directions = list(path_directions) or ([True] if path_points else [])
            if len(directions) != len(paths):
                return {"error": "path_directions needs one entry per path."}

            harness, err = self._active_harness(doc)
            if err:
                return err
            wire = harness.Wires.Add(len(paths), paths, directions, description)
            return {
                "status": "created",
                "type": "wire",
                "name": com_get(wire, "Name"),
                "num_paths": len(paths),
                "wire_index": harness.Wires.Count - 1,
                "description": description,
            }
        except Exception as e:
            return error_result(e)

    def _add_group(
        self,
        kind: str,
        path_indices: list[int],
        path_directions: list[bool],
        member_indices: list[int],
        split_path_indices: list[int] | None,
        split_path_directions: list[bool] | None,
        description: str,
        path_points: list[list[float]] | None,
    ) -> dict[str, Any]:
        """Add a cable or bundle: harness paths plus the harness wires it holds.

        Cables.Add / Bundles.Add(NumberOfPaths, PathArray, PathDirectionArray,
        NumberOfWires, WireArray, SplitPathArray, SplitPathDirectionArray,
        ConductorDescription) take harness paths and Wire objects as plain
        lists; empty lists for the split paths (Solid Edge 2026).
        """
        try:
            doc = self.doc_manager.get_active_document()
            err = self._require_assembly(doc)
            if err:
                return err
            paths, err = self._harness_paths(doc, path_indices, path_points, kind)
            if err:
                return err
            directions = list(path_directions) or ([True] if path_points else [])
            if len(directions) != len(paths):
                return {"error": "path_directions needs one entry per path."}
            harness, err = self._active_harness(doc)
            if err:
                return err
            wires, err = self._harness_items(harness.Wires, member_indices, "wire")
            if err:
                return err
            if not wires:
                return {"error": f"A {kind} needs the 0-based indices of the harness wires in it."}
            split_paths, err = self._harness_paths(doc, split_path_indices or [], None, kind)
            if err and split_path_indices:
                return err
            split_dirs = list(split_path_directions or [True] * len(split_paths))
            if len(split_dirs) != len(split_paths):
                return {"error": "split_path_directions needs one entry per split path."}

            collection = harness.Cables if kind == "cable" else harness.Bundles
            item = collection.Add(
                len(paths),
                paths,
                directions,
                len(wires),
                wires,
                split_paths,
                split_dirs,
                description,
            )
            return {
                "status": "created",
                "type": kind,
                "name": com_get(item, "Name"),
                "num_paths": len(paths),
                "num_wires": len(wires),
                "description": description,
            }
        except Exception as e:
            return error_result(e)

    def add_cable(
        self,
        path_indices: list[int],
        path_directions: list[bool],
        wire_indices: list[int],
        split_path_indices: list[int] | None = None,
        split_path_directions: list[bool] | None = None,
        description: str = "",
        path_points: list[list[float]] | None = None,
    ) -> dict[str, Any]:
        """Add a cable holding harness wires along harness paths.

        path_indices / split_path_indices index AssemblyDocument.Paths and
        wire_indices the harness wires, all 0-based; path_points makes the
        path through [x, y, z] points (meters) instead.
        """
        return self._add_group(
            "cable",
            path_indices,
            path_directions,
            wire_indices,
            split_path_indices,
            split_path_directions,
            description,
            path_points,
        )

    def add_bundle(
        self,
        path_indices: list[int],
        path_directions: list[bool],
        conductor_indices: list[int],
        split_path_indices: list[int] | None = None,
        split_path_directions: list[bool] | None = None,
        description: str = "",
        path_points: list[list[float]] | None = None,
    ) -> dict[str, Any]:
        """Add a bundle of harness wires along harness paths.

        conductor_indices index the harness wires (0-based); paths as for
        add_cable.
        """
        return self._add_group(
            "bundle",
            path_indices,
            path_directions,
            conductor_indices,
            split_path_indices,
            split_path_directions,
            description,
            path_points,
        )
