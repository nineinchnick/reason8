from datetime import date
from pathlib import Path

import pytest

from reason8 import cli
from reason8.paths import (
    REPO_ROOT,
    LayoutError,
    data_dir,
    file_date,
    find_files,
    partition,
    partition_in_range,
    partitioned_name,
    partitioned_path,
    require_partitioned,
    unpartitioned_files,
)

REPLAY = "2026-11-01_10-26-55-123_Supreme Isthmus v2.1_2026.09.03.sdfz"


def test_data_dir_defaults_to_the_repository(monkeypatch):
    monkeypatch.delenv("REASON8_DATA_DIR", raising=False)
    assert data_dir() == REPO_ROOT / "data"
    assert (REPO_ROOT / "pyproject.toml").is_file()


def test_data_dir_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("REASON8_DATA_DIR", str(tmp_path))
    assert data_dir() == Path(tmp_path)


def test_partition_is_the_date_the_name_starts_with():
    assert file_date(REPLAY) == date(2026, 11, 1)
    assert partition(REPLAY) == "date=2026-11-01"
    assert partitioned_name(REPLAY) == f"date=2026-11-01/{REPLAY}"
    assert partitioned_path(Path("data/replays"), REPLAY) == Path(
        f"data/replays/date=2026-11-01/{REPLAY}"
    )
    for undated in ("game.sdfz", "20261101_102655_Map_2026.09.03.sdfz", "2026-13-01_x.sdfz", ""):
        assert file_date(undated) is None
        assert partition(undated) == "date=unknown"


def test_partition_in_range():
    assert partition_in_range("date=2026-11-01")
    assert partition_in_range("date=unknown")
    assert not partition_in_range("other")
    november = {"since": date(2026, 11, 1), "until": date(2026, 12, 1)}
    assert partition_in_range("date=2026-11-01", **november)
    assert partition_in_range("date=2026-11-30", **november)
    assert not partition_in_range("date=2026-12-01", **november)
    assert not partition_in_range("date=2026-10-31", **november)
    assert not partition_in_range("date=unknown", since=date(2026, 11, 1))


def test_find_files_in_partitions_and_flat(tmp_path):
    for relative_path in (
        "date=2026-11-02/2026-11-02_b.sdfz",
        "date=2026-11-01/2026-11-01_a.sdfz",
        "date=unknown/test.sdfz",
        "2026-10-01_flat.sdfz",
        "date=2026-11-01/2026-11-01_a.sdfz.part",
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    names = [path.name for path in find_files(tmp_path, "*.sdfz")]
    assert names == ["2026-10-01_flat.sdfz", "2026-11-01_a.sdfz", "2026-11-02_b.sdfz", "test.sdfz"]
    since = [path.name for path in find_files(tmp_path, "*.sdfz", since=date(2026, 11, 2))]
    assert since == ["2026-11-02_b.sdfz"]
    assert [path.name for path in unpartitioned_files(tmp_path, "*.sdfz")] == [
        "2026-10-01_flat.sdfz"
    ]
    with pytest.raises(LayoutError, match="1 files"):
        require_partitioned(tmp_path, "*.sdfz")
    require_partitioned(tmp_path / "date=2026-11-01", "*.json.zst")
    require_partitioned(tmp_path / "missing", "*.sdfz")


def test_the_cli_reports_a_flat_layout(tmp_path, capsys):
    (tmp_path / "2026-11-01_flat.jsonl.gz").write_bytes(b"")
    arguments = ["headless", "batch", "--data-dir", str(tmp_path), "--out-dir", str(tmp_path)]
    assert cli.main(arguments) == 2
    assert "migrate-layout" in capsys.readouterr().err
