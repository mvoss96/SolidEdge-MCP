"""Connected shapes, reference lines, extra relations and sketch dimensions."""

import math
from unittest.mock import MagicMock

import pytest


def _line(start, end, name="line"):
    line = MagicMock(name=name)
    line.GetStartPoint.return_value = start
    line.GetEndPoint.return_value = end
    return line


def _collection(items):
    coll = MagicMock()
    coll.Count = len(items)
    coll.Item.side_effect = lambda i: items[i - 1]
    return coll


class _AxisDim:
    """A distance dimension whose value depends on MeasurementAxisDirection."""

    def __init__(self, x, y, y_first):
        self.x, self.y = x, y
        self.MeasurementAxisDirection = y_first
        self.MeasurementAxisEx = 2
        self.Constraint = False
        self.deleted = False

    @property
    def Value(self):
        return self.y if self.MeasurementAxisDirection else self.x

    @Value.setter
    def Value(self, value):
        if self.MeasurementAxisDirection:
            self.y = value
        else:
            self.x = value

    def Delete(self):
        self.deleted = True


@pytest.fixture
def sm():
    from solidedge_mcp.backends.sketching import SketchManager

    dm = MagicMock()
    doc = MagicMock()
    doc.RefPlanes.Count = 3
    dm.get_active_document.return_value = doc
    manager = SketchManager(dm)
    manager.active_profile = MagicMock()
    return manager


class TestConnectedShapes:
    def test_rectangle_welds_its_corners_and_sets_directions(self, sm):
        lines = sm.active_profile.Lines2d
        edges = [MagicMock(name=f"e{i}") for i in range(4)]
        lines.AddBy2Points.side_effect = edges
        lines.Count = 4

        result = sm.draw_rectangle(0.0, 0.0, 0.04, 0.02)

        rel = sm.active_profile.Relations2d
        assert [c.args for c in rel.AddKeypoint.call_args_list] == [
            (edges[0], 1, edges[1], 0),
            (edges[1], 1, edges[2], 0),
            (edges[2], 1, edges[3], 0),
            (edges[3], 1, edges[0], 0),
        ]
        assert [c.args for c in rel.AddHorizontal.call_args_list] == [(edges[0],), (edges[2],)]
        assert [c.args for c in rel.AddVertical.call_args_list] == [(edges[1],), (edges[3],)]
        assert result["elements"] == [["line", 1], ["line", 2], ["line", 3], ["line", 4]]

    def test_rectangle_indices_follow_existing_lines(self, sm):
        lines = sm.active_profile.Lines2d
        lines.AddBy2Points.side_effect = [MagicMock() for _ in range(4)]
        lines.Count = 6

        result = sm.draw_rectangle(0.0, 0.0, 0.04, 0.02)

        assert result["elements"] == [["line", 3], ["line", 4], ["line", 5], ["line", 6]]

    def test_polygon_welds_its_corners(self, sm):
        lines = sm.active_profile.Lines2d
        edges = [MagicMock(name=f"e{i}") for i in range(3)]
        lines.AddBy2Points.side_effect = edges
        lines.Count = 3

        result = sm.draw_polygon(0.0, 0.0, 0.01, 3)

        rel = sm.active_profile.Relations2d
        assert rel.AddKeypoint.call_count == 3
        assert rel.AddKeypoint.call_args_list[-1].args == (edges[2], 1, edges[0], 0)
        assert result["elements"] == [["line", 1], ["line", 2], ["line", 3]]

    def test_line_and_circle_report_their_index(self, sm):
        sm.active_profile.Lines2d.Count = 5
        sm.active_profile.Circles2d.Count = 2

        assert sm.draw_line(0, 0, 1, 0)["element"] == ["line", 5]
        assert sm.draw_circle(0, 0, 1)["element"] == ["circle", 2]


class TestReferenceLines:
    def test_ref_element_projects_once_and_is_reused(self, sm):
        ref = MagicMock(name="ref_line")
        sm.active_profile.ProjectRefPlane.return_value = ref
        sm.active_profile.Lines2d = _collection([MagicMock()])

        sm.add_constraint("Colinear", [["line", 1], ["ref", 3]])
        sm.add_constraint("Colinear", [["line", 1], ["ref", 3]])

        sm.active_profile.ProjectRefPlane.assert_called_once()
        assert sm.active_profile.Relations2d.AddColinear.call_args.args[1] is ref

    def test_project_ref_plane_names_the_element(self, sm):
        result = sm.project_ref_plane(2)
        assert result["element"] == ["ref", 2]

    def test_a_new_sketch_forgets_the_old_reference_lines(self, sm):
        sm.ref_lines[3] = MagicMock()
        sm.create_sketch_on_plane_index(1)
        assert sm.ref_lines == {}

    def test_an_invalid_plane_is_an_error(self, sm):
        sm.active_profile.Lines2d = _collection([MagicMock()])
        result = sm.add_constraint("Colinear", [["line", 1], ["ref", 9]])
        assert "Invalid plane_index" in result["error"]


class TestNewRelations:
    @pytest.fixture
    def two_lines(self, sm):
        a, b = MagicMock(name="a"), MagicMock(name="b")
        sm.active_profile.Lines2d = _collection([a, b])
        return a, b

    def test_point_on_passes_the_keypoint(self, sm, two_lines):
        a, b = two_lines
        result = sm.add_constraint("PointOn", [["line", 1], ["line", 2]], keypoint1=1)
        sm.active_profile.Relations2d.AddPointOn.assert_called_once_with(a, 1, b)
        assert result["keypoint1"] == 1

    def test_equal_direction_passes_both_keypoints(self, sm, two_lines):
        a, b = two_lines
        sm.add_constraint("EqualDirection", [["line", 1], ["line", 2]], keypoint1=1, keypoint2=0)
        sm.active_profile.Relations2d.AddEqualDirection.assert_called_once_with(a, 1, b, 0)

    def test_colinear(self, sm, two_lines):
        a, b = two_lines
        sm.add_constraint("Colinear", [["line", 1], ["line", 2]])
        sm.active_profile.Relations2d.AddColinear.assert_called_once_with(a, b)

    def test_colinear_needs_two_elements(self, sm, two_lines):
        result = sm.add_constraint("Colinear", [["line", 1]])
        assert "needs 2 elements" in result["error"]


class TestAddDimension:
    @pytest.fixture
    def dims(self, sm):
        dim = MagicMock(name="dim")
        dim.Value = 0.04
        dim.Constraint = False
        profile_dims = sm.active_profile.Dimensions
        for member in (
            "AddLength",
            "AddRadius",
            "AddCircularDiameter",
            "AddDistanceBetweenObjects",
            "AddAngleBetweenObjects",
        ):
            getattr(profile_dims, member).return_value = dim
        variables = sm.doc_manager.get_active_document.return_value.Variables
        variables.GetName.return_value = "Dimension 12"
        return profile_dims, dim, variables

    def test_length_is_driving_and_takes_the_value(self, sm, dims):
        profile_dims, dim, _ = dims
        line = _line((0, 0), (0.04, 0))
        sm.active_profile.Lines2d = _collection([line])

        result = sm.add_sketch_dimension("length", [["line", 1]], value=0.04)

        profile_dims.AddLength.assert_called_once_with(line)
        assert dim.Constraint is True
        assert result["value"] == 0.04
        assert result["variable"] == "Dimension 12"
        assert "error" not in result

    def test_a_value_solid_edge_does_not_keep_is_reported(self, sm, dims):
        _, dim, _ = dims
        sm.active_profile.Lines2d = _collection([_line((0, 0), (0.04, 0))])

        class Sticky:
            Value = 0.04
            Constraint = False

            def __setattr__(self, key, val):
                if key != "Value":
                    object.__setattr__(self, key, val)

        sm.active_profile.Dimensions.AddLength.return_value = Sticky()
        result = sm.add_sketch_dimension("length", [["line", 1]], value=0.05)
        assert "over-constrained" in result["error"]

    def test_name_and_formula_go_through_variables(self, sm, dims):
        _, dim, variables = dims
        sm.active_profile.Lines2d = _collection([_line((0, 0), (0.04, 0))])
        variables.GetName.return_value = "Breite"

        result = sm.add_sketch_dimension("length", [["line", 1]], name="Breite", formula="W / 2")

        variables.PutName.assert_called_once_with(dim, "Breite")
        variables.Edit.assert_called_once_with("Breite", "W / 2")
        assert result["variable"] == "Breite"

    def test_distance_from_a_horizontal_line_to_a_ref_line_measures_y(self, sm, dims):
        profile_dims, dim, _ = dims
        line = _line((0.01, 0.02), (0.05, 0.02))
        ref = _line((-1.0, 0.0), (1.0, 0.0), "ref")
        sm.active_profile.Lines2d = _collection([line])
        sm.active_profile.ProjectRefPlane.return_value = ref

        dim.Value = 0.02
        result = sm.add_sketch_dimension("distance", [["line", 1], ["ref", 3]], value=0.02)

        args = profile_dims.AddDistanceBetweenObjects.call_args.args
        assert args[0] is line and args[5] is ref
        assert args[1:5] == (pytest.approx(0.03), 0.02, 0.0, False)
        assert args[6:10] == (pytest.approx(0.03), pytest.approx(0.0), 0.0, False)
        assert dim.MeasurementAxisDirection is True
        assert result["axis"] == "y"

    def test_distance_from_a_keypoint_uses_its_coordinates(self, sm, dims):
        profile_dims, dim, _ = dims
        line = _line((0.01, 0.02), (0.05, 0.02))
        ref = _line((0.0, -1.0), (0.0, 1.0), "ref")
        sm.active_profile.Lines2d = _collection([line])
        sm.active_profile.ProjectRefPlane.return_value = ref

        dim.Value = 0.05
        result = sm.add_sketch_dimension("distance", [["line", 1], ["ref", 2]], keypoint1=1)

        args = profile_dims.AddDistanceBetweenObjects.call_args.args
        assert args[1:5] == (0.05, 0.02, 0.0, True)
        assert dim.MeasurementAxisDirection is False
        assert result["axis"] == "x"

    def test_the_direction_is_flipped_when_it_measures_the_other_axis(self, sm, dims):
        profile_dims, _, _ = dims
        sm.active_profile.Lines2d = _collection([_line((0.01, 0.02), (0.05, 0.02))])
        sm.active_profile.ProjectRefPlane.return_value = _line((-1.0, 0.0), (1.0, 0.0))
        dim = _AxisDim(x=0.047, y=0.02, y_first=False)
        profile_dims.AddDistanceBetweenObjects.return_value = dim

        result = sm.add_sketch_dimension("distance", [["line", 1], ["ref", 3]])

        assert result["value"] == 0.02
        assert result["axis"] == "y"

    def test_two_keypoints_along_x_switch_the_axis_to_explicit(self, sm, dims):
        profile_dims, _, _ = dims
        sm.active_profile.Lines2d = _collection(
            [_line((0.01, 0.01), (0.05, 0.01)), _line((0.05, 0.04), (0.01, 0.04))]
        )
        dim = _AxisDim(x=0.04, y=0.03, y_first=False)
        profile_dims.AddDistanceBetweenObjects.return_value = dim

        result = sm.add_sketch_dimension(
            "distance", [["line", 1], ["line", 2]], keypoint1=0, keypoint2=0, axis="x"
        )

        assert dim.MeasurementAxisEx == 3  # igDimAxisModeExplicit
        assert result["value"] == 0.04

    def test_a_distance_that_measures_neither_axis_is_removed(self, sm, dims):
        profile_dims, _, _ = dims
        sm.active_profile.Lines2d = _collection([_line((0.01, 0.02), (0.05, 0.02))])
        sm.active_profile.ProjectRefPlane.return_value = _line((-1.0, 0.0), (1.0, 0.0))
        dim = _AxisDim(x=0.047, y=0.033, y_first=False)
        profile_dims.AddDistanceBetweenObjects.return_value = dim

        result = sm.add_sketch_dimension("distance", [["line", 1], ["ref", 3]])

        assert "was removed" in result["error"]
        assert dim.deleted

    def test_a_consumed_profile_is_ended_and_the_model_rolled_forward(self, sm, dims):
        sm.active_profile.Lines2d = _collection([_line((0, 0), (0.04, 0))])
        sm.accumulated_profiles.append(sm.active_profile)
        sm.active_end_flags = 1
        sm.clear_accumulated_profiles()
        doc = sm.doc_manager.get_active_document.return_value
        doc.Models.Count = 1
        doc.DesignEdgebarFeatures.Count = 5

        result = sm.add_sketch_dimension("length", [["line", 1]], value=0.04)

        sm.active_profile.End.assert_called_once_with(1)
        doc.Models.Item.return_value.Recompute.assert_called_once()
        doc.DesignEdgebarFeatures.Item.assert_called_with(5)
        doc.DesignEdgebarFeatures.Item.return_value.RollToFeature.assert_called_once()
        assert result["model_recomputed"] is True

    def test_an_unconsumed_profile_is_left_alone(self, sm, dims):
        sm.active_profile.Lines2d = _collection([_line((0, 0), (0.04, 0))])
        result = sm.add_sketch_dimension("length", [["line", 1]])
        sm.active_profile.End.assert_not_called()
        assert "model_recomputed" not in result

    def test_a_circle_is_measured_from_its_centre(self, sm, dims):
        profile_dims, _, _ = dims
        circle = MagicMock(name="circle")
        circle.GetCenterPoint.return_value = (0.03, 0.01)
        sm.active_profile.Circles2d = _collection([circle])
        sm.active_profile.ProjectRefPlane.return_value = _line((0.0, -1.0), (0.0, 1.0))

        sm.add_sketch_dimension("distance", [["circle", 1], ["ref", 2]], axis="x")

        args = profile_dims.AddDistanceBetweenObjects.call_args.args
        assert args[1:5] == (0.03, 0.01, 0.0, True)

    def test_angle_takes_and_reports_degrees(self, sm, dims):
        profile_dims, dim, _ = dims
        dim.Value = math.radians(90)
        sm.active_profile.Lines2d = _collection(
            [_line((0, 0), (0.04, 0)), _line((0.04, 0), (0.04, 0.02))]
        )

        result = sm.add_sketch_dimension("angle", [["line", 1], ["line", 2]])

        profile_dims.AddAngleBetweenObjects.assert_called_once()
        assert result["measured"] == pytest.approx(90)

    def test_diameter_uses_the_circular_diameter(self, sm, dims):
        profile_dims, _, _ = dims
        circle = MagicMock(name="circle")
        sm.active_profile.Circles2d = _collection([circle])

        sm.add_sketch_dimension("diameter", [["circle", 1]], value=0.01)

        profile_dims.AddCircularDiameter.assert_called_once_with(circle)

    def test_a_length_needs_a_line(self, sm, dims):
        sm.active_profile.Circles2d = _collection([MagicMock()])
        result = sm.add_sketch_dimension("length", [["circle", 1]])
        assert "takes a line" in result["error"]

    def test_wrong_element_count(self, sm, dims):
        sm.active_profile.Lines2d = _collection([MagicMock()])
        result = sm.add_sketch_dimension("distance", [["line", 1]])
        assert "takes 2 element(s)" in result["error"]

    def test_no_sketch(self):
        from solidedge_mcp.backends.sketching import SketchManager

        result = SketchManager(MagicMock()).add_sketch_dimension("length", [["line", 1]])
        assert "No active sketch" in result["error"]
