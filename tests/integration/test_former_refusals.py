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
