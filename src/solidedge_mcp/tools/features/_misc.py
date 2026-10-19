"""Miscellaneous feature tools (thicken, pattern, mirror, face ops, etc.)."""

from typing import Any, Literal

from solidedge_mcp.backends.validation import validate_numerics
from solidedge_mcp.managers import feature_manager


def thicken(
    method: Literal["basic", "sync"] = "basic",
    thickness: float = 0.0,
    direction: str = "Both",
    surface_index: int = 0,
) -> dict[str, Any]:
    """Thicken a construction surface into a solid.

    basic: Models.AddThickenFeature over the faces of construction surface
    surface_index (0-based, in document order; make one with
    create_extruded_surface first). thickness in meters; direction is
    'Both' | 'Normal' | 'Reverse'. sync makes the same call (Thickens.AddSync
    lives on a Model, and a surface-only document has none).
    """
    err = validate_numerics(thickness=thickness)
    if err:
        return err
    match method:
        case "basic":
            return feature_manager.thicken_surface(
                thickness=thickness, direction=direction, surface_index=surface_index
            )
        case "sync":
            return feature_manager.create_thicken_sync(
                thickness=thickness, direction=direction, surface_index=surface_index
            )
        case _:
            return {"error": f"Unknown method: {method}"}


def create_pattern(
    method: Literal[
        "rectangular_ex",
        "circular_ex",
        "duplicate",
        "by_fill",
        "by_table",
        "by_table_sync",
        "by_fill_ex",
        "by_curve_ex",
        "user_defined",
    ] = "rectangular_ex",
    feature_name: str = "",
    x_count: int = 1,
    y_count: int = 1,
    x_spacing: float = 0.0,
    y_spacing: float = 0.0,
    count: int = 1,
    angle: float = 360.0,
    axis_x: float = 0.0,
    axis_y: float = 0.0,
    axis_z: float = 0.0,
    x_offsets: list[float] | None = None,
    y_offsets: list[float] | None = None,
    curve_edge_index: int = 0,
    spacing: float = 0.0,
    plane_index: int = 1,
    rectangle_angle: float = 0.0,
) -> dict[str, Any]:
    """Pattern an existing feature, selected by name (see list_features).

    rectangular_ex: x_count/y_count + x_spacing/y_spacing (meters), the
    1-based plane_index the grid sits on (1=Top/XY, 2=Right/YZ, 3=Front/XZ)
    and rectangle_angle (degrees, grid rotation). circular_ex: count instances
    (original included, >= 2) spread over angle (degrees, default 360) around
    an axis through (axis_x, axis_y, axis_z) (meters), normal to plane_index.
    by_fill / by_fill_ex: fill the closed active sketch (the region, drawn
    and closed after the feature) on an x_spacing by y_spacing grid.
    user_defined: feature_name alone. duplicate, by_table, by_table_sync and
    by_curve_ex are unsupported (instance references, Excel tables, curve
    anchors); use rectangular_ex, circular_ex or by_fill.
    """
    err = validate_numerics(
        x_spacing=x_spacing,
        y_spacing=y_spacing,
        angle=angle,
        axis_x=axis_x,
        axis_y=axis_y,
        axis_z=axis_z,
        spacing=spacing,
        rectangle_angle=rectangle_angle,
    )
    if err:
        return err
    match method:
        case "rectangular_ex":
            return feature_manager.create_pattern_rectangular_ex(
                feature_name=feature_name,
                x_count=x_count,
                y_count=y_count,
                x_spacing=x_spacing,
                y_spacing=y_spacing,
                plane_index=plane_index,
                rectangle_angle=rectangle_angle,
            )
        case "circular_ex":
            return feature_manager.create_pattern_circular_ex(
                feature_name=feature_name,
                count=count,
                angle=angle,
                plane_index=plane_index,
                axis_x=axis_x,
                axis_y=axis_y,
                axis_z=axis_z,
            )
        case "duplicate":
            return feature_manager.create_pattern_duplicate(feature_name=feature_name)
        case "by_fill":
            return feature_manager.create_pattern_by_fill(
                feature_name=feature_name, x_spacing=x_spacing, y_spacing=y_spacing
            )
        case "by_table":
            return feature_manager.create_pattern_by_table(
                feature_name=feature_name, x_offsets=x_offsets or [], y_offsets=y_offsets or []
            )
        case "by_table_sync":
            return feature_manager.create_pattern_by_table_sync(
                feature_name=feature_name, x_offsets=x_offsets or [], y_offsets=y_offsets or []
            )
        case "by_fill_ex":
            return feature_manager.create_pattern_by_fill_ex(
                feature_name=feature_name, x_spacing=x_spacing, y_spacing=y_spacing
            )
        case "by_curve_ex":
            return feature_manager.create_pattern_by_curve_ex(
                feature_name=feature_name,
                curve_edge_index=curve_edge_index,
                count=count,
                spacing=spacing,
            )
        case "user_defined":
            return feature_manager.create_user_defined_pattern(feature_name=feature_name)
        case _:
            return {"error": f"Unknown method: {method}"}


def create_mirror(
    method: Literal["basic", "sync_ex", "save_as_part"] = "basic",
    feature_name: str = "",
    mirror_plane_index: int = 3,
    new_file_name: str = "",
    link_to_original: bool = True,
    overwrite: bool = False,
    feature_names: list[str] | None = None,
) -> dict[str, Any]:
    """Mirror features across a reference plane, or save a mirrored part.

    mirror_plane_index is 1-based (1=Top/XY, 2=Right/YZ, 3=Front/XZ, 4+ = user
    planes). feature_name (see list_features): basic/sync_ex. basic also takes
    feature_names to mirror several features into one MirrorCopy; it works in
    ordered and synchronous parts (synchronous: only features created while
    the part was synchronous). new_file_name
    (absolute .par path) and link_to_original: save_as_part, which needs
    overwrite=true to replace an existing file.
    'sync_ex' (unsupported: MirrorCopies.AddSyncEx answers E_FAIL); use 'basic'.
    """
    if mirror_plane_index < 1:
        return {
            "error": (
                f"mirror_plane_index must be >= 1 (got {mirror_plane_index}); "
                "plane indices are 1-based (1=Top/XY, 2=Right/YZ, 3=Front/XZ)."
            )
        }
    match method:
        case "basic":
            names = list(feature_names or [])
            if feature_name and feature_name not in names:
                names.insert(0, feature_name)
            return feature_manager.create_mirror(
                feature_names=names, mirror_plane_index=mirror_plane_index
            )
        case "sync_ex":
            return feature_manager.create_mirror_sync_ex(
                feature_name=feature_name, mirror_plane_index=mirror_plane_index
            )
        case "save_as_part":
            return feature_manager.save_as_mirror_part(
                new_file_name=new_file_name,
                overwrite=overwrite,
                mirror_plane_index=mirror_plane_index,
                link_to_original=link_to_original,
            )
        case _:
            return {"error": f"Unknown method: {method}"}


def face_operation(
    type: Literal["rotate_by_points", "rotate_by_edge"] = "rotate_by_points",
    face_index: int = 0,
    vertex1_index: int = 0,
    vertex2_index: int = 0,
    edge_index: int = 0,
    angle: float = 0.0,
) -> dict[str, Any]:
    """Rotate a face of the solid body about an axis.

    angle in degrees. All indices are 0-based. rotate_by_points takes the axis
    from vertex1_index/vertex2_index; rotate_by_edge takes it from edge_index.
    """
    err = validate_numerics(angle=angle)
    if err:
        return err
    match type:
        case "rotate_by_points":
            return feature_manager.create_face_rotate_by_points(
                face_index=face_index,
                vertex1_index=vertex1_index,
                vertex2_index=vertex2_index,
                angle=angle,
            )
        case "rotate_by_edge":
            return feature_manager.create_face_rotate_by_edge(
                face_index=face_index, edge_index=edge_index, angle=angle
            )
        case _:
            return {"error": f"Unknown type: {type}"}


def add_body(
    method: Literal["basic", "by_mesh", "feature", "construction", "by_tag"] = "basic",
    body_type: Literal["Solid", "Part", "SheetMetal", "Construction"] = "Solid",
    body_name: str = "",
    import_file_path: str = "",
    construction_index: int = 0,
    tag: str = "",
) -> dict[str, Any]:
    """Add a new body to the part document.

    basic: body_type is passed to Models.AddBody ('Solid'/'Part',
    'SheetMetal', 'Construction') along with body_name (defaults to 'Body').
    feature: import_file_path, the absolute path of the file to import the
    body from (required). construction: construction_index, 0-based into
    doc.Constructions. by_tag: tag. 'by_mesh' (unsupported: needs an array
    of facet vertex coordinates; import the mesh in the Solid Edge UI).
    """
    match method:
        case "basic":
            return feature_manager.add_body(body_type=body_type, body_name=body_name)
        case "by_mesh":
            return feature_manager.add_body_by_mesh()
        case "feature":
            return feature_manager.add_body_feature(import_file_name=import_file_path)
        case "construction":
            return feature_manager.add_by_construction(construction_index=construction_index)
        case "by_tag":
            return feature_manager.add_body_by_tag(tag=tag)
        case _:
            return {"error": f"Unknown method: {method}"}


def simplify(
    method: Literal["auto", "enclosure", "duplicate", "local_enclosure"] = "auto",
) -> dict[str, Any]:
    """Simplify the model for downstream use (lighter assembly representation).

    auto: in an assembly, builds its simplified representation from every
    occurrence; a part is refused. The other methods are unsupported:
    AddSimplifyEnclosure, AddSimplifyDuplicate and AddLocalSimplifyEnclosure
    need assembly occurrences or topology proxies from a user selection.
    """
    match method:
        case "auto":
            return feature_manager.auto_simplify()
        case "enclosure":
            return feature_manager.simplify_enclosure()
        case "duplicate":
            return feature_manager.simplify_duplicate()
        case "local_enclosure":
            return feature_manager.local_simplify_enclosure()
        case _:
            return {"error": f"Unknown method: {method}"}


def manage_feature(
    action: Literal["delete", "suppress", "unsuppress", "reorder", "rename", "convert"] = "delete",
    index: int | None = None,
    target_index: int | None = None,
    after: bool = True,
    new_name: str = "",
    feature_name: str = "",
    target_type: str = "",
) -> dict[str, Any]:
    """Manage entries in the feature tree (delete, suppress, reorder, rename).

    The feature is selected by feature_name or by index, a 0-based position in
    the feature tree (see list_features); one of them is required. If both are
    given they must name the same feature. reorder moves that feature to
    target_index (required; 'after' places it behind the target). rename uses
    new_name. convert selects the feature by feature_name and needs
    target_type: 'cutout' or 'protrusion'.
    Deleting a feature is destructive and removes its geometry.
    """
    if action == "reorder" and target_index is None:
        return {"error": "reorder needs target_index (0-based, see list_features)."}
    resolved = 0
    if action in ("delete", "suppress", "unsuppress", "reorder", "rename"):
        found, err = feature_manager.resolve_feature_index(index=index, feature_name=feature_name)
        if err or found is None:
            return err or {"error": "Feature could not be resolved."}
        resolved = found
    match action:
        case "delete":
            return feature_manager.delete_feature(index=resolved)
        case "suppress":
            return feature_manager.feature_suppress(index=resolved)
        case "unsuppress":
            return feature_manager.feature_unsuppress(index=resolved)
        case "reorder":
            assert target_index is not None
            return feature_manager.feature_reorder(
                index=resolved, target_index=target_index, after=after
            )
        case "rename":
            return feature_manager.feature_rename(index=resolved, new_name=new_name)
        case "convert":
            return feature_manager.convert_feature_type(
                feature_name=feature_name, target_type=target_type
            )
        case _:
            return {"error": f"Unknown action: {action}"}


def create_draft_angle(
    face_index: int,
    angle: float,
    plane_index: int = 1,
    side: Literal["inside", "outside"] = "inside",
) -> dict[str, Any]:
    """Add a draft (taper) to a face, pulled from a reference plane.

    angle in degrees. face_index is 0-based. plane_index is the 1-based draft
    (parting) plane: 1=Top/XY, 2=Right/YZ, 3=Front/XZ. side is which way the
    face tapers.
    """
    err = validate_numerics(angle=angle)
    if err:
        return err
    return feature_manager.create_draft_angle(
        face_index=face_index, angle=angle, plane_index=plane_index, side=side
    )
