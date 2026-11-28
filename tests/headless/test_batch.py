"""Tests for the batch's list of replays."""

from pathlib import Path

from reason8.headless import batch


def test_read_list_skips_comments_and_empty_lines(tmp_path):
    listed = tmp_path / "replays.txt"
    listed.write_text(
        "# from the context sample\n"
        "/replays/date=2026-11-01/a.sdfz\n"
        "\n"
        "  /replays/date=2026-11-02/b.sdfz  \n"
        "#/replays/date=2026-11-03/c.sdfz\n"
    )
    assert batch.read_list(listed) == [
        Path("/replays/date=2026-11-01/a.sdfz"),
        Path("/replays/date=2026-11-02/b.sdfz"),
    ]
