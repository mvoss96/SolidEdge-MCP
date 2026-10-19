"""Connected shapes, reference lines, extra relations and sketch dimensions."""

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
