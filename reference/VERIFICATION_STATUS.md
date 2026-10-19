# Verification Status

**Last measured: 2026-10-19**, against Solid Edge 2026 (226.00.01.04), branch `fix/unsupported-tools`.

Regenerate every number here with the commands in [How to re-measure](#how-to-re-measure).
Nothing in this document is an estimate.

## Why this document exists

`TYPELIB_IMPLEMENTATION_MAP.md` tracks a different question — *is this COM API
wired up?* — and answers 96%. That measure has been wrong in the same direction
repeatedly: it counts a tool as done when the call exists, and this server's
defining bug class is **a call that exists, returns `status: "created"`, and
changes nothing**.

Six assembly-level creators were counted as implemented and had never once been
able to run: they consume a sketch profile, and no sketch could be created in an
assembly at all. Nothing failed. They reported "No profiles available", which
reads like a caller mistake.

So this document tracks the other question: **does it actually do what it says?**

## Where we are

| | count | what it means |
|---|---|---|
| Tools | 119 | the MCP action surface |
| Resources | 53 + 2 guides | read-only `solidedge://` endpoints |
| Unit tests | 3,023 (12 skip) | mocked COM; catch shape, not truth |
| Integration tests | 105 | drive real Solid Edge; 16 in `test_former_refusals.py` pin tools that used to refuse; 19 pin exact values against a known box, 7 pin the wrong-member and lost-value fixes, 11 pin the synchronous flange, the split, the thicken, the slot, the bead, the lofted flange and the mirror only the volume can see, 5 pin 3D sketch lines, structural frames along them (both methods) and planar relations through References, and there are assembly, draft and sheet-metal fixtures |
| Structural audits | 7 | all at zero but one documented finding |

### Creator verification

Two decorator families snapshot the document before and after a creator runs
and downgrade a false success to an explicit error. `@verifies_geometry` (and
`@verifies_assembly_geometry`) watch the body's face count and, since
2026-09-17, the total body volume -- a mirror of a box across its own face is
a wider box with the same six faces, and read as a no-op until the volume was
in the snapshot; for creators that build no solid -- a plane, a surface, a sketch, a document -- that count never
moves, so `@verifies_collection_growth(...)` watches the COM collection their
`Add` lands in instead. This is the only kind of check that catches a call
which succeeds and builds nothing.

| | count | |
|---|---|---|
| Verified live | **176** | the body or the target collection must change, or the result becomes an error |
| Refuse honestly | 37 | return `unsupported: True` -- 34 outright, plus 3 that refuse one argument value and otherwise work (`create_extrude`/`create_revolve` with `operation="Intersect"`, `create_revolve_full` with a treatment) |
| Neither | **0** | |
| **Total `create_*`** | **213** | |

Of the 176, 126 are face-count checks and 50 are collection-growth checks:
15 reference planes (`RefPlanes`), 14 surfaces (the five `Constructions.*Surfaces`
summed), 1 split (`Models.*.Splits`, because the first model keeps its faces), 9 that reshape or annotate (`Models.*.Etches`, `.Threads`, `.Drafts`,
`.FaceRotates`; `PartsLists`, `DraftBendTables`), 3 surface blends
(`Models.*.Rounds` + `.Blends`), 2 sketches (`ProfileSets`), and 6 document
creators (`Application.Documents`). Each group was driven live: the snapshot
reads a real integer on the right document type, a known-good creator moves
it and passes through, and a creator that claims success without adding is
downgraded to an error on the live path -- not only against fakes.

### Structural audits

All seven are ratchets: a new violation fails the suite.

| audit | catches | status |
|---|---|---|
| `audit_com_signatures` | wrong argument count | 0 |
| `audit_com_receivers` | a real member read off the wrong interface | 1 known (`SaveAsPLMXML`) |
| `audit_com_writes` | assignment to a method or read-only property | 0 |
| `audit_com_hasattr` | `hasattr` probes of COM members | 0 |
| `audit_reported_writes` | a swallowed write reported as applied | 0 |
| `audit_com_enum_args` | a value outside the enum its parameter declares | 0 |
| `audit_dead_params` | a parameter declared and never read | 0 |

## What is left

Ordered by how much risk each removes, not by effort.

### 1. Live verification is reproducible for what has been fixed, not for everything

**80 integration tests across 10 files.** They pin the known-answer box, the
reported values and units, the document creators and fixtures, drawing views,
the tier-1 features, and -- added in the live-fix round of 2026-09-17 --
`tests/integration/test_wrong_members_and_lost_values.py`: the face rotates,
the planar-face refusal of `delete_blend`, a revolve angle found and set in
degrees, the symbol-file origin round trip, and the swept-surface refusal;
`test_synchronous_flange_split_thicken.py`: a flange in a synchronous
document (and the ordered refusal leaving no dead feature), a split by a
reference plane, and a thicken for all three sides. Each was mutation-tested
when written. Most tools still have no integration
test of their own; `scripts/live_sweep.py` is what drives all 119 once, and
its record (below) is the coverage that exists for the rest.

### 2. Numeric correctness -- checked, the last item closed

`tests/integration/test_known_answer_box.py` builds a 0.08 x 0.048 x 0.03 m box
and asserts, at float-noise tolerance, every number that can be computed by
hand: volume, surface area, each face area, counts, bounding box, centre of
gravity, mass at two densities, the body diagonal, a right angle, and the six
global moments of inertia with their frame (about the model origin) and sign
(products positive) -- plus five cross-path invariants that need no reference
value. Nineteen of nineteen pass live.

Writing it found and fixed: vertices reported as one-element points (`result[0]`
of a flat `(x, y, z)`); a short physical-property tuple padded with zeros and
reported as computed; a partial surface-area sum reported as the total; moments
of inertia that silently assumed steel; `GetDirection{1,2}Extent` read with its
slots shifted so the side constant was reported as the distance and the real
value stringified into a non-existent `face_ref`; a cone `half_angle` and the
camera's perspective field of view reported in radians.

**Closed (2026-09-17):** an angular variable holds radians. The revolve's own
angle dimension (`RevolvedProtrusion_1_FiniteAngle`, system name `Dimension 346`)
reads 1.5707963 for 90 degrees and `UnitsType` reports `igUnitAngle`. It was
invisible before because `Variables.Query` was called with
`NamedBy=seVariableNameByUser`, which sees only user-named variables, and
`Variables.Item(i)` enumerates a dimension as a nameless entry; `ByBoth` and
`Item("<display name>")` reach it. `Variable.Units` is a member of nothing --
the read of it was suppressed on every variable, so no units were ever
reported. Variables now carry `units`, `units_type` and, for angles,
`value_degrees`; `set_variable` takes degrees for an angular variable.

### 3. Known-broken, with the evidence

How the argument shapes were found without the SDK: the install's Training
folder holds parts with every feature this server could not build, and a
feature made in the UI reports its parameters. `Training/JigSaw/JS-0005.PSM`
gave the bead its side constants; `sesscfl.psm`, `Pin1.par` and the transition
parts gave the louver, thread, contour flange and lofted flange the values
they were then retried with -- and still refused with, which is what makes
those refusals final on this install.

`scripts/live_sweep.py` drives all 119 tools through the real server and
records every outcome in `reference/LIVE_SWEEP.md`. The latest run, on
2026-09-18 for the `0.1.0rc1` candidate with everything of the 17th and 18th
in (synchronous flanges with a bend deduction, splits, thickens, slots, beads,
lofted flanges, 3D sketch lines, structural frames, assembly relations through
References, select-all on drafts): **116 OK, 16 refuse honestly, 2 FAIL, 0 NOOP**
across 134 cases (from 93 / 15 / 14 / 2 on 2026-09-16). The remaining FAILs are the sweep's
own deliberate probes -- a missing macro, a plane asked for NURBS data -- each
answered with an explanation. Seven earlier FAIL rows were the sweep's
inputs, not the tools (a planar face for `delete_blend`, a circle where a
louver needs a line, a constraint without its elements, ...); they were
corrected so the record separates the two. The run of 2026-10-19 on `fix/unsupported-tools`:
**133 OK, 6 refuse honestly, 3 FAIL, 0 NOOP** across 142 cases; the three
FAILs are the same deliberate probes (a missing macro, `manage_feature`
without a target, a plane asked for NURBS data). What the sweep and the probes
behind it leave as known-broken, each with the evidence that closes the
question on this install:

| tool / method | evidence |
|---|---|
| `simplify(method="auto")` | `Models.AddAutoSimplify(1, [model.Body], True, "")` took the Solid Edge 2026 process down (RPC_S_CALL_FAILED, then the server gone); the parameter wants occurrences. In a part it still refuses before COM; in an assembly it now builds the simplified representation (below). |
| `create_blend` | `Blends.Add(1, SelectSetArray, RadiusArray, ...)` answers `E_FAIL` with nested edge arrays plain or VARIANT-wrapped, one edge or a face's four (Solid Edge 2026). `create_round` takes the same edges through `Rounds.Add`. Retried 2026-10-19 in ordered and synchronous parts: a face, a face's `Edges` collection, the document `SelectSet` holding the edge, face pairs, edges as `VT_ARRAY | VT_DISPATCH` through raw `Invoke`, with the optional arrays given as `VT_DISPATCH`/`VT_VARIANT`/`VT_I4` -- `E_FAIL`; `NumberOfSelectSets` > 1 answers `E_POINTER`, nested edge arrays `RPC_E_SERVERFAULT` (Solid Edge survived). No training part holds a Blend to copy from. Refuses before COM. |
| `create_thread` (basic, physical) | `Threads.Add(HoleData, 1, [cylinder], [end face])` answers `E_INVALIDARG` for an extruded boss and for a cut hole alike, with every `HoleData` this server can build -- including one the online reference's route fills in (`Standard = "ISO Metric"`, `Size`, `ThreadDataByDescription`, a depth method and depth) and every adjacent end face. The Siemens developer community reports the same since 2016 ("NOTHING WORKED" across VB.NET and C++ array shapes; advice: file an incident) -- [Parameters for Threads.Add Method](https://community.sw.siemens.com/s/question/0D54O000061xqWfSAI/parameters-for-threadsadd-method). Retried 2026-10-19 in ordered and synchronous parts: the end as a face or an edge, the arrays as `VT_ARRAY` of `VT_DISPATCH`/`VT_UNKNOWN`/`VT_VARIANT` (also by reference) through raw `Invoke`, `AddEx` alike; in `Training/Pin1.par` even the `HoleData` of the UI-made `Thread_1` is refused for every cylinder/face pair, so the `HoleData` is not the cause. The refusal used to point at `create_hole(method='threaded')`, which does not exist; it now names the UI Thread command. Refuses before COM. |
| `create_contour_flange` (sync, sync_with_bend, sync_ex) | `ContourFlanges.AddSync`, `AddSyncByBendDeductionOrBendAllowance` and `AddSyncEx` all answer `E_INVALIDARG` in a synchronous document with the open line from the tab edge on the perpendicular base plane. Refuse before COM. |
| `create_louver` (sync) | `Louvers.AddSync` on a synchronous tab's top face answers 0x807B0086. Refuses before COM. |
| `create_contour_flange` (ex) | `ContourFlanges.AddEx` and `Add` answer `E_FAIL` to 52 open-profile placements: from the tab's corner and from the interior of an edge, on the base planes and on planes perpendicular to the edge, both projection sides. Retried 2026-10-19: a line from the tab's corner on `RefPlanes.AddNormalToCurve(edge, igCurveStart, ...)`, both directions, `igToEndOfEdge` and `igFinite`, both sides, and `ChainedEdgeSet` as the edge, a `VT_DISPATCH` array or a list (the list answers `RPC_E_SERVERFAULT`) -- `E_FAIL`. In `Training/JigSaw/JS-0005.PSM`, with `ContourFlange_1` suppressed, the same line on its own profile plane with its own values (`igToEndOfEdge`, side 2, its bend radius) answers `E_FAIL` too. Refuses before COM. |
| `create_bounded_surface` | `BlueSurfs.Add` answers `E_INVALIDARG` to profiles from `ProfileSets` (all this server's sketches) whatever `Origins` holds, typed or through raw `Invoke` with by-reference `SAFEARRAY(VT_DISPATCH)`. With profiles from `doc.Sketches` it builds two circles (`igNatural` tangents, no guides, `Status` OK) and answers `E_FAIL` for two rectangles, with or without keypoint relations and line origins (2026-10-19). Re-adding the bounded surface of `Training/JigSaw/JS-0023.PAR` from its own sections answers `E_FAIL`. Refuses before COM and points at `create_lofted_surface`. |
| `create_primitive_cutout` in an ordered part | `CylinderFeatures.AddCutoutByCenterAndRadius` and `BoxFeatures.AddCutoutByCenter` answer `E_INVALIDARG` in an ordered part with every `ProfileSide`/`ExtentSide`, and still do after `ModelingMode` is switched to synchronous (a synchronous feature does not cut ordered geometry; the same call cuts a synchronous box, 6 -> 7 faces). Solid Edge has no ordered primitive. Refuses before COM and names `create_extruded_cutout` / `create_revolved_cutout`; the refusal no longer mentions an `allow_mode_switch` parameter no tool has. |
| `create_assembly_swept_protrusion` | `E_INVALIDARG` with `Origins` as inner VARIANTs (the shape the part-level sweep needs) and `E_FAIL` as plain tuples or lists; the argument shape is not the cause. |

Turned from refusals into working creators on 2026-09-17, each driven live and
pinned: `select_set(action='all')` on a draft (`SelectSet.AddAll` is a 2D sheet call -- Siemens' only example is a draft with an active sheet -- and selects every sheet entity there; a part or assembly answers E_FAIL -- since 2026-10-19 those add each feature-tree entry or occurrence with `SelectSet.Add` instead); `add_assembly_relation(planar|axial)`, `add_assembly_constraint(mate|align|planar_align|axial_align)` (`AssemblyDocument.CreateReference(occurrence, face)` wraps a face of the occurrence's part document in the Reference that `Relations3d.AddPlanar`/`AddAxial` want -- Siemens' "Working with References" page; faces, RefPlanes and AsmRefPlanes handed over directly all answered 0x80040225. Planar constraining points are the faces' range midpoints. Two placed boxes mate, two cylinders go coaxial: Relations3d grows by one); `create_lofted_flange` (basic, advanced: `Models.AddLoftedFlange` with `Origins` = each section's first `Line2d`/`Arc2d` object, `OriginRefs` = `igStart` per section and `igNFType` last -- the community sample's shape, verified on this server's own profiles; two open lines on parallel planes give a 6-face sheet); `create_stamped(bead)` (`Beads.Add` with the cross-section a UI-made bead
reports -- circular, rounded, punched ends -- and `BeadSide` = the two
`*SideDummy` members; igLeft/igRight answer E_FAIL; 6 -> 20 faces on the base
plane and on a plane through the sheet face alike); `create_slot` (`Slots.Add` along an open line with a finite or
through-all extent cuts, 6 -> 10 faces; `igLeft` and a closed profile record a
slot that removes nothing, so `direction='Reverse'` refuses); `draw_3d_line`
(`Sketches3D.Add()` + `Lines3D.Add(x1, y1, z1, x2, y2, z2)`, a new tool) and
`structural_frame` along those lines, both methods (`StructuralFrames.Add`
and `AddByOrientation` with an empty coordinate-system name build along one
and two lines -- and raises an informational "Segments group
... 3D Draw" dialog on the first frame of a session that blocks the call until
OK is clicked, so `backends/dialogs.py` dismisses exactly that dialog while
the call runs); `create_flange(method='sync')` (above); `create_split(plane_index)`
(`Splits.Add(1, [model.Body], 1, [RefPlane], 0, 0)` splits the box into two
design bodies, Models 1 -> 2); `thicken(method='basic')`
(`Models.AddThickenFeature` over `Constructions.Item(n).Body.Faces` turns an
extruded surface into a 12-face solid for all three sides -- the surface's own
`Faces` property raises; `thicken(method='sync')` makes the same call, since
`Thickens.AddSync` lives on a Model and a surface-only document has none).

Turned from a refusal into a working creator on 2026-10-19:
`create_pattern(method='circular_ex')` (`Patterns.AddByCircularEx(1, [feature],
RefPlane, count, angle, [x, y, z], sePatternFitOffset, 0, False, seSmartPattern)`
through the type-library wrapper; the axis runs through the 3D `AxisPoint`
normal to the plane, a 2D point answers `E_INVALIDARG`). The call was driven
live by direct COM in an ordered part (16 spokes, 50 teeth, a pattern of 5
holes, all over 360 degrees); the tool path itself has unit tests only so far.
`create_mirror(method='basic')` in an ordered part: it called only
`MirrorCopies.AddSync`, which mirrors synchronous geometry and refused or
recorded an empty `MirrorCopy` for ordered features. An ordered part now goes
through `MirrorCopies.Add(RefPlane, n, [features])`, verified by direct COM to
add exactly the mirrored volume; a synchronous part keeps `AddSync`.
`query_component(property='interference')` was refused as unreachable. It
calls `AssemblyDocument.CheckInterference` through `IDispatch.Invoke`: the
type-library wrapper marshals Set1 as a VARIANT array (`DISP_E_TYPEMISMATCH`),
`VARIANT(VT_ARRAY | VT_DISPATCH, occurrences)` is accepted; the `[out]`
interference arrays answer `E_INVALIDARG` and are omitted, so the result is
parsed from the report file Solid Edge writes. Verified by direct COM on a
13-occurrence assembly (German UI); the parser is unit-tested against that
report's structure.

Turned from refusals into working tools on branch `fix/unsupported-tools`
(2026-10-19), each driven live and pinned by an integration test:
`create_document(type='weldment')` builds a weldment assembly
(`WeldmentAssembly = True`) with `Documents.Add("SolidEdge.AssemblyDocument",
template)`, the template being the one
`Application.GetDefaultTemplatePath(igWeldmentAssemblyDocument)` names (the
legacy `SolidEdge.WeldmentDocument` ProgID wants a `.pwd` template, and
`GetDefaultTemplatePath(igWeldmentDocument)` names only the template folder). The template must be a Windows path next to the
ProgID: a path alone answers `CO_E_CLASSSTRING`, forward slashes `E_INVALIDARG`.
`convert_by_file_path` opens the Solid Edge input without a window
(`Documents.Open(path, 0x8)`), writes it with `SaveCopyAs` and closes it; an
already open document is used and left open. `Application.ConvertByFilePath`
itself (typelib help: "Converts all the files with given ext. from given
folder/path ...") shows a progress bar, returns `True` and writes nothing for a
file, a folder, `*.par` -> `*.stp` patterns and STEP -> `.par` alike. A STEP
input does not open in the background (`E_FAIL`) and is refused towards
`import_file`.
`select_set(action='all')` in a part, sheet-metal part or assembly:
`SelectSet.AddAll` answers `E_FAIL` there typed, late-bound and through raw
`Invoke`, and Solid Edge has no 3D select-all command (`*EditSelectAll` = 40023
exists only for drafts, layouts and profiles). Each `DesignEdgebarFeatures`
entry (part) or occurrence (assembly) now goes in through `SelectSet.Add`; a
draft keeps `AddAll`.
`create_normal_cutout(method='finite')` on a part: the refusal said a finite
normal cutout is sheet-metal only, because the call passed the sheet-metal
method `igSMFaceCutout` (205), which answers `E_FAIL` on a part.
`NormalCutouts.AddFiniteMulti(1, [profile], side, depth, 0)` cuts in an ordered
part (a 4 mm circle 10 mm deep removes exactly its cylinder); sheet metal keeps
205.
`create_flange`, all six ordered methods (basic, by_match_face, by_face,
with_bend_calc, match_face_with_bend, by_face_with_bend): every ordered
`Flanges.Add*` records `OffsetType = 0` when the optional `OffsetType` is not
passed (the MatchFace calls have no such parameter), and that flange never
solves. A flange made in the UI (`Training/FanPlate.psm`, `Foot1.psm`, ...)
carries `OffsetType = igNone` (44); setting `Flange.OffsetType = 44` after the
call makes each of them build on an ordered base tab (6 -> 10 faces, `Status`
igFeatureOK, `BendRadius`, `BendAngle` in radians and a bend deduction read
back). The `*BendDeductionOrBendAllowance` calls take `VT_EMPTY` in their
keypoint slots (`None` answers `E_POINTER`); `AddFlangeByFace*` takes the sheet
face that holds the edge as reference. An edge on a thin side face answers
`E_POINTER`.
`create_louver(method='basic')`: `Louvers.Add` solves only when its profile
lies on a plane whose parent is the sheet face. The louver in
`Training/sesscfl.psm` has `ProfileDefiningFace` = a Face and its plane has
`ParentPlane` = that face; API louvers added in that document on its plane
build (111 -> 119 faces), on a `RefPlane` parallel to Top at the same height
they do not. The tool copies the sketch's lines onto
`RefPlanes.AddParallelByDistance(sheet face, 0, igRight)` (coordinates through
`Convert2DCoordinate`/`Convert3DCoordinate`, since that plane's axes differ)
and builds from the copy: 6 -> 14 faces on an ordered tab, top or bottom face,
both height directions. Some depth/height pairs still do not solve (6 mm deep
and 5.5 mm high, 2 mm and 1 mm, on 1 mm material); that louver is deleted and
reported.
`create_lofted_surface` (basic, v2): `LoftedSurfaces.Add`/`Add2` answered
`E_INVALIDARG` because `CrossSectionTypes` went in as a plain list, which
pywin32 marshals as an array of VARIANTs. As `VARIANT(VT_ARRAY | VT_I4, ...)`
the call builds a solved surface from two circles (`Status` igFeatureOK), with
the coordinate origins `create_loft` uses and `igNone` extents and tangents.
`wiring(type='wire')`: `Wires.Add` routes along `AssemblyDocument.Paths`
entries (harness paths); occurrences and 3D sketch lines answer `E_FAIL`.
`Paths.Add(n, [igSpacePoint]*n, [None]*n, [igKeyPointPointOnly]*n, xyz...,
seKeypointEndConditionNatural, seKeypointEndConditionNatural)` makes a path
through space points (without the optional `EndpointEndType` it answers
`E_INVALIDARG`), and `Harness.Wires.Add(1, [path], [True], "")` adds the wire.
The tool takes `path_points`; `path_indices` now index `AssemblyDocument.Paths`.
`cable` and `bundle` still pass occurrences as paths and were not retried.
`create_swept_surface(method='basic')` no longer calls `SweptSurfaces.Add`,
which took the Solid Edge process down on 3 of 5 calls once a session had been
through a few documents. It goes through `SweptSurfaces.AddEx`, the call
`method='ex'` already made (coordinate-array origins, `OriginRefs` `None`):
three builds in fresh documents late in a long session, plus the integration
test, all solved, no crash.
`simplify(method='auto')` in an assembly calls
`AssemblyDocument.CreateOrEditSimplifiedAssembly(0, [], 0.0, n, occurrences)`
with every occurrence included: `IsAssemblySimplified` goes False -> True.

Fixed in the live-fix round of 2026-09-17, each driven live and pinned:
`face_operation` (both rotates) raised `E_INVALIDARG` because `FaceRotates.Add`
was given the wrong members of `FaceRotateConstants` (1, 1, 2 and 2, 1, 0 for
ByGeometry=2, RecreateBlends=6, AxisEnd=4 / ByPoints=1, None=0 -- the comments
beside the literals named the members correctly and the values wrongly);
`delete_topology(blend)` accepted a planar face and built nothing (a cylinder
face removes the round, 26 -> 23 faces) and now refuses the planar one;
`draft_config(get_origin)` lost its values because `GetSymbolFileOrigin`'s
parameters are declared `[in]` and the late-bound call returns `None` -- it now
goes through `InvokeTypes` with `[in, out]` by-reference doubles, and says
plainly when no origin is set (`DISP_E_BADINDEX`, inside `excepinfo`); the
variables findings above.

Fixed because the earlier sweep found them: vertices came back as one-element
points; extent slots were shifted so the side constant was reported as the
distance; `create_assembly_hole` passed no hole data and Solid Edge recorded
nothing (with a `HoleData` it cuts, faces 6 -> 7); the two assembly protrusions
take no scope parts and were being measured against occurrence bodies they
cannot touch (they are recorded, `ExtrudedProtrusions.Count` 0 -> 1, and are
now verified by that); eight surface creators refused without a solid on a
precondition Solid Edge does not have.

### 4. The swallow surface is only partly audited

771 `except Exception` and 210 `contextlib.suppress` in the backends. The
write-then-reported slice is pinned by `audit_reported_writes`. The read side was
measured and is clean: only 10 swallowed reads have a literal fallback and 9 of
those fall back to `None`, which a caller can tell apart from a real value.

### 5. What CI actually protects

`.github/workflows/ci.yml` runs ruff, format, mypy and `pytest -q` only.
Integration tests are deselected by `addopts`, there is no Solid Edge on the
runner, and the seven audits live inside unit tests that **skip when
`reference/typelib_dump.json` is absent** -- and it is gitignored. On CI every
audit is inert and no COM call is ever made. Green CI is a far weaker signal
than green locally: the live suite, the audits and `scripts/live_sweep.py` are
the gates that matter, and they run only where Solid Edge does.

### 6. What is shipped

`modernize` is pushed to `origin` and carries the first release candidate,
`0.1.0rc1` (2026-09-18, `CHANGELOG.md`, tag `v0.1.0rc1`). `master` has not moved
since the merge of #3. No PR.

## What "done" would mean

There is no state where this is finished, because Solid Edge keeps its own
counsel. A defensible bar:

- [x] every tool driven live at least once, with the result recorded (`scripts/live_sweep.py` -> `reference/LIVE_SWEEP.md`)
- [x] every bug fixed this far pinned by a test that fails without the fix (80 integration tests, each mutation-tested when written)
- [x] the 49 unverified creators given a collection-growth check
- [x] one numeric-correctness check per measurement tool (angular variables included, see above)
- [ ] the branch merged

## How to re-measure

```bash
uv run pytest -q                       # unit
uv run pytest -m integration -q        # needs a running, licensed Solid Edge
uv run ruff check . && uv run mypy src/
for a in signatures receivers writes hasattr enum_args dead_params; do
  uv run python scripts/audit_com_$a.py
done
uv run python scripts/audit_reported_writes.py
```

```bash
uv run python scripts/count_verified_creators.py   # the creator table above
```

Do not count creators with a grep for a decorator name. There are two
decorator families and two class-level forms that cover whole mixins, and a
grep for one name has undercounted this table twice.
