"""Tests for ``reason8 sync`` against moto's in-memory S3 (no network, no real AWS)."""

from datetime import UTC, date, datetime

import pytest

from reason8 import cli
from reason8.data.download import MANIFEST_NAME, manifest_bytes, merge_manifests, read_manifest
from reason8.data.storage import Bucket, configured_bucket
from reason8.data.sync import PULL, PUSH, is_area_name, sync_area
from reason8.paths import LayoutError, partitioned_name
from reason8.replays.parse import index_text, merge_indexes, parse_index
from reason8.replays.tables import INDEX_NAME

NEW = "2026-11-01_10-00-00-000_new.sdfz"
SAME = "2026-11-01_11-00-00-000_same.sdfz"
GROWN = "2026-11-02_10-00-00-000_grown.sdfz"
ONLY_IN_BUCKET = "2026-11-03_10-00-00-000_only.sdfz"


def put(bucket, relative_path, data):
    bucket.client.put_object(Bucket=bucket.name, Key=bucket.key(relative_path), Body=data)


def all_keys(bucket):
    response = bucket.client.list_objects_v2(Bucket=bucket.name)
    return sorted(listed["Key"] for listed in response.get("Contents", []))


def write(directory, name, data):
    """Write a data file into its date partition under ``directory``."""
    path = directory / partitioned_name(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def manifest_row(match_id, status="ok", updated_at=datetime(2026, 11, 1, tzinfo=UTC)):
    return {
        "match_id": match_id,
        "replay_file_name": f"{match_id}.sdfz",
        "status": status,
        "attempts": 1,
        "updated_at": updated_at,
    }


def sync(bucket, data_directory, area_name, direction, **options):
    return sync_area(
        bucket,
        area_name,
        direction,
        data_directory=data_directory,
        log=lambda line: None,
        **options,
    )


def test_bucket_uri():
    assert Bucket("s3://name", client=object()).key("replays/a.sdfz") == "replays/a.sdfz"
    with_prefix = Bucket("s3://name/some/prefix/", client=object())
    assert (with_prefix.name, with_prefix.key("parsed/b")) == ("name", "some/prefix/parsed/b")
    for wrong in ("name", "s3://", "https://name"):
        with pytest.raises(ValueError):
            Bucket(wrong, client=object())


def test_s3_is_opt_in(monkeypatch):
    monkeypatch.delenv("REASON8_S3_URI", raising=False)
    assert configured_bucket() is None
    monkeypatch.setenv("REASON8_S3_URI", "s3://from-environment")
    assert configured_bucket().name == "from-environment"
    assert configured_bucket("s3://from-option").name == "from-option"


def test_sync_without_a_bucket_fails(monkeypatch, capsys):
    monkeypatch.delenv("REASON8_S3_URI", raising=False)
    assert cli.main(["sync", "push"]) == 2
    assert "REASON8_S3_URI" in capsys.readouterr().err


def test_push_copies_new_and_changed_files_and_deletes_nothing(bucket, tmp_path):
    replays = tmp_path / "replays"
    write(replays, NEW, b"new replay")
    write(replays, SAME, b"same")
    write(replays, GROWN, b"complete replay")
    write(replays, GROWN + ".part", b"half")
    write(replays, "notes.txt", b"not data")
    # in a partition that is not its own: not copied
    (replays / "date=2026-11-02" / "2026-11-05_10-00-00-000_misplaced.sdfz").write_bytes(b"x")
    put(bucket, f"replays/{partitioned_name(SAME)}", b"SAME")  # same size: not copied
    put(bucket, f"replays/{partitioned_name(GROWN)}", b"truncated")
    put(bucket, f"replays/{partitioned_name(ONLY_IN_BUCKET)}", b"kept")

    summary = sync(bucket, tmp_path, "replays", PUSH)

    assert (summary.files, summary.already_there, summary.copied) == (3, 1, 2)
    assert summary.bytes == len(b"new replay") + len(b"complete replay")
    assert bucket.read(f"replays/date=2026-11-01/{NEW}") == b"new replay"
    assert bucket.read(f"replays/date=2026-11-02/{GROWN}") == b"complete replay"
    assert bucket.read(f"replays/date=2026-11-01/{SAME}") == b"SAME"
    assert all_keys(bucket) == [
        f"shared/replays/date=2026-11-01/{NEW}",
        f"shared/replays/date=2026-11-01/{SAME}",
        f"shared/replays/date=2026-11-02/{GROWN}",
        f"shared/replays/date=2026-11-03/{ONLY_IN_BUCKET}",
    ]
    again = sync(bucket, tmp_path, "replays", PUSH)
    assert (again.already_there, again.copied, again.merged) == (3, 0, [])


def test_pull_copies_missing_files_and_deletes_nothing(bucket, tmp_path):
    first, second = "2026-11-01.games.parquet", "2026-11-02.games.parquet"
    put(bucket, f"tables/{partitioned_name(first)}", b"games a")
    put(bucket, f"tables/{partitioned_name(second)}", b"games b")
    put(bucket, "tables/date=2026-11-01/2026-11-01_old.json.zst", b"earlier format")
    put(bucket, "tables/date=2026-11-01/nested/2026-11-01.chat.parquet", b"in a subdirectory")
    put(bucket, f"replays/{partitioned_name('2026-11-01_a.sdfz')}", b"another area")
    tables_dir = tmp_path / "tables"
    local_only = write(tables_dir, "2026-11-01.players.parquet", b"kept")

    summary = sync(bucket, tmp_path, "tables", PULL, jobs=2)

    assert (summary.files, summary.copied) == (2, 2)
    assert sorted(path.relative_to(tables_dir).as_posix() for path in tables_dir.rglob("*")) == [
        "date=2026-11-01",
        f"date=2026-11-01/{first}",
        "date=2026-11-01/2026-11-01.players.parquet",
        "date=2026-11-02",
        f"date=2026-11-02/{second}",
    ]
    assert (tables_dir / partitioned_name(first)).read_bytes() == b"games a"
    assert local_only.read_bytes() == b"kept"
    assert sync(bucket, tmp_path, "tables", PULL).copied == 0


def test_match_and_dry_run(bucket, tmp_path):
    for name in ("2026-10-01_a.sdfz", "2026-11-01_b.sdfz", "2026-11-02_c.sdfz"):
        put(bucket, f"replays/{partitioned_name(name)}", name.encode())
    put(bucket, f"replays/{MANIFEST_NAME}", manifest_bytes([manifest_row(1)]))

    planned = sync(bucket, tmp_path, "replays", PULL, match="2026-11-*", dry_run=True)
    assert (planned.files, planned.copied) == (2, 2)
    assert not (tmp_path / "replays").exists()

    assert sync(bucket, tmp_path, "replays", PULL, match="2026-11-*").merged == []
    assert sorted(path.name for path in (tmp_path / "replays").rglob("*.sdfz")) == [
        "2026-11-01_b.sdfz",
        "2026-11-02_c.sdfz",
    ]


def test_since_and_until_select_partitions(bucket, tmp_path):
    for name in ("2026-10-31_a.sdfz", "2026-11-01_b.sdfz", "2026-11-02_c.sdfz", "test.sdfz"):
        put(bucket, f"replays/{partitioned_name(name)}", name.encode())
    put(bucket, f"replays/{MANIFEST_NAME}", manifest_bytes([manifest_row(1)]))
    put(bucket, "matches/matches.parquet", b"dump")

    window = {"since": date(2026, 11, 1), "until": date(2026, 11, 2)}
    summary = sync(bucket, tmp_path, "replays", PULL, **window)
    assert (summary.files, summary.copied, summary.merged) == (1, 1, [])
    assert [path.name for path in (tmp_path / "replays").rglob("*.sdfz")] == ["2026-11-01_b.sdfz"]
    # areas without partitions have nothing in a date range
    assert sync(bucket, tmp_path, "matches", PULL, **window).files == 0
    # without a range, undated files are in date=unknown
    sync(bucket, tmp_path, "replays", PULL)
    assert (tmp_path / "replays" / "date=unknown" / "test.sdfz").read_bytes() == b"test.sdfz"


def test_a_flat_layout_stops_the_sync(bucket, tmp_path):
    put(bucket, "replays/2026-11-01_flat.sdfz", b"flat")
    with pytest.raises(LayoutError, match="bucket"):
        sync(bucket, tmp_path, "replays", PULL)
    assert not (tmp_path / "replays").exists()

    put(bucket, "tables/date=2026-11-01/2026-11-01.games.parquet", b"partitioned")
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    (tables_dir / "2026-11-01.chat.parquet").write_bytes(b"flat")
    with pytest.raises(LayoutError, match="data directory"):
        sync(bucket, tmp_path, "tables", PUSH)
    with pytest.raises(LayoutError, match="data directory"):
        sync(bucket, tmp_path, "tables", PULL)


def test_manifests_are_merged_both_ways(bucket, tmp_path):
    replays = tmp_path / "replays"
    replays.mkdir()
    earlier, later = datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC)
    local_rows = [manifest_row(1), manifest_row(2, "error", earlier)]
    bucket_rows = [manifest_row(2, "ok", later), manifest_row(3)]
    (replays / MANIFEST_NAME).write_bytes(manifest_bytes(local_rows))
    put(bucket, f"replays/{MANIFEST_NAME}", manifest_bytes(bucket_rows))

    assert sync(bucket, tmp_path, "replays", PUSH).merged == [MANIFEST_NAME]
    in_bucket = read_manifest(bucket.read(f"replays/{MANIFEST_NAME}"))
    assert {match_id: row["status"] for match_id, row in in_bucket.items()} == {
        1: "ok",
        2: "ok",
        3: "ok",
    }
    # push wrote only to the bucket
    assert set(read_manifest(replays / MANIFEST_NAME)) == {1, 2}

    assert sync(bucket, tmp_path, "replays", PULL).merged == [MANIFEST_NAME]
    assert set(read_manifest(replays / MANIFEST_NAME)) == {1, 2, 3}
    assert sync(bucket, tmp_path, "replays", PULL).merged == []
    assert sync(bucket, tmp_path, "replays", PUSH).merged == []


def test_manifest_is_copied_when_the_other_side_has_none(bucket, tmp_path):
    put(bucket, f"replays/{MANIFEST_NAME}", manifest_bytes([manifest_row(7)]))
    assert sync(bucket, tmp_path, "replays", PULL).merged == [MANIFEST_NAME]
    assert set(read_manifest(tmp_path / "replays" / MANIFEST_NAME)) == {7}


def test_merge_manifests_keeps_the_later_row():
    earlier, later = datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC)
    destination = manifest_bytes([manifest_row(1, "ok", later)])
    assert merge_manifests(destination, manifest_bytes([manifest_row(1, "error", earlier)])) is None
    merged = merge_manifests(
        manifest_bytes([manifest_row(1, "error", earlier)]),
        manifest_bytes([manifest_row(1, "ok", later), manifest_row(2)]),
    )
    rows = read_manifest(merged)
    assert (rows[1]["status"], set(rows)) == ("ok", {1, 2})


def test_merge_indexes_prefers_the_source_and_keeps_the_rest():
    destination = index_text(
        {
            "a.sdfz": {"file": "a.sdfz", "status": "error"},
            "b.sdfz": {"file": "b.sdfz", "status": "ok"},
        }
    ).encode()
    source = index_text({"a.sdfz": {"file": "a.sdfz", "status": "ok"}}).encode()
    merged = parse_index(merge_indexes(destination, source).decode())
    assert {name: entry["status"] for name, entry in merged.items()} == {
        "a.sdfz": "ok",
        "b.sdfz": "ok",
    }
    assert merge_indexes(destination, destination) is None


def test_index_is_merged_on_push(bucket, tmp_path):
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    (tables_dir / INDEX_NAME).write_text(index_text({"a.sdfz": {"file": "a.sdfz", "status": "ok"}}))
    put(bucket, f"tables/{INDEX_NAME}", index_text({"b.sdfz": {"file": "b.sdfz"}}).encode())
    assert sync(bucket, tmp_path, "tables", PUSH).merged == [INDEX_NAME]
    assert set(parse_index(bucket.read(f"tables/{INDEX_NAME}").decode())) == {"a.sdfz", "b.sdfz"}


def test_cli_sync(bucket, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REASON8_DATA_DIR", str(tmp_path))
    (tmp_path / "matches").mkdir()
    (tmp_path / "matches" / "matches.parquet").write_bytes(b"dump")
    # the CLI makes its own client; moto intercepts it too
    uri = f"s3://{bucket.name}/{bucket.prefix}"
    assert cli.main(["sync", "push", "matches", "--s3-uri", uri]) == 0
    assert bucket.read("matches/matches.parquet") == b"dump"
    assert "matches: 1 files, 0 already there, 1 copied" in capsys.readouterr().err
    assert cli.main(["sync", "pull", "nonsense", "--s3-uri", uri]) == 2


def test_state_areas_copy_state_files_and_their_tables(bucket, tmp_path):
    game = "2026-11-01_10-00-00-000_Map_2026.09.03"
    state = tmp_path / "state-v7"
    write(state, game + ".jsonl.gz", b"state")
    write(state, game + ".game.parquet", b"game table")
    write(state, game + ".game.parquet.part", b"half")
    # the batch's scratch folder inside a partition: not copied
    scratch = state / "date=2026-11-01" / "state-abc123"
    scratch.mkdir()
    (scratch / "state.jsonl").write_bytes(b"x")

    summary = sync(bucket, tmp_path, "state-v7", PUSH)

    assert (summary.files, summary.copied) == (2, 2)
    assert all_keys(bucket) == [
        f"shared/state-v7/date=2026-11-01/{game}.game.parquet",
        f"shared/state-v7/date=2026-11-01/{game}.jsonl.gz",
    ]
    pulled = sync(bucket, tmp_path / "elsewhere", "state-v7", PULL)
    assert pulled.copied == 2
    assert (
        tmp_path / "elsewhere" / "state-v7" / "date=2026-11-01" / (game + ".jsonl.gz")
    ).is_file()


@pytest.mark.parametrize(
    ("area_name", "expected"),
    [
        ("state", True),
        ("state-v7", True),
        ("replays", True),
        ("state-", False),
        ("state-../x", False),
    ],
)
def test_area_names(area_name, expected):
    assert is_area_name(area_name) is expected
