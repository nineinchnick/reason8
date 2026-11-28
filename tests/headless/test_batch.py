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


def test_play_passes_the_options_to_the_engine_run_and_keeps_the_state(tmp_path, monkeypatch):
    seen = {}

    def fake_play(arguments):
        seen["arguments"] = arguments
        Path(arguments.out).write_text('{"t":"header"}\n')
        return {"exit_code": 0, "timed_out": False, "desyncs": 0}

    monkeypatch.setattr(batch.headless_run, "play", fake_play)
    monkeypatch.setattr(batch.tables, "convert", lambda path: {"bytes": {"game": 1}})
    target = tmp_path / "date=2026-11-01" / "a.jsonl.gz"
    target.parent.mkdir()
    options = batch.PlayOptions(
        data_dir=tmp_path / "bar", max_frame=36000, timeout=60, settings=("A=1",)
    )
    result = batch.play(tmp_path / "a.sdfz", target, options)
    assert result["ok"] and result["state_file"] == str(target) and target.is_file()
    arguments = seen["arguments"]
    assert (arguments.max_frame, arguments.timeout, arguments.set) == (36000, 60, ["A=1"])
    assert arguments.data_dir == str(tmp_path / "bar") and arguments.snapshots
