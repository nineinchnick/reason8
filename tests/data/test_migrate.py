"""Tests for ``reason8 storage migrate-layout`` on temporary directories and moto's S3."""

from reason8 import cli
from reason8.data.migrate import migrate_bucket, migrate_local
from reason8.data.sync import PULL, sync_area
from reason8.paths import partitioned_name

FIRST = "2026-11-01_10-00-00-000_Rosetta 1.4.4_2026.09.03.sdfz"
SECOND = "2026-11-02_10-00-00-000_Rosetta 1.4.4_2026.09.03.sdfz"
UNDATED = "game.sdfz"


def quiet(line):
    pass


def flat_replays(directory):
    replays = directory / "replays"
    replays.mkdir(parents=True)
    for name in (FIRST, SECOND, UNDATED):
        (replays / name).write_bytes(name.encode())
    (replays / "manifest.parquet").write_bytes(b"manifest")
    (replays / (FIRST + ".part")).write_bytes(b"half")
    return replays


def tree(directory):
    return sorted(path.relative_to(directory).as_posix() for path in directory.rglob("*.*"))


def test_local_dry_run_changes_nothing(tmp_path):
    replays = flat_replays(tmp_path)
    before = tree(replays)
    lines = []
    summary = migrate_local(replays, "*.sdfz", log=lines.append)
    assert (summary.flat, summary.moved, summary.bytes) == (3, 3, len(FIRST + SECOND + UNDATED))
    assert tree(replays) == before
    assert lines[0] == f"would move {replays / FIRST} -> {replays / 'date=2026-11-01' / FIRST}"


def test_local_migration_moves_files_into_partitions(tmp_path):
    replays = flat_replays(tmp_path)
    summary = migrate_local(replays, "*.sdfz", apply=True, log=quiet)
    assert (summary.moved, summary.left) == (3, [])
    assert tree(replays) == sorted(
        [
            f"date=2026-11-01/{FIRST}",
            f"date=2026-11-02/{SECOND}",
            f"date=unknown/{UNDATED}",
            "manifest.parquet",
            FIRST + ".part",
        ]
    )
    assert (replays / partitioned_name(FIRST)).read_bytes() == FIRST.encode()
    again = migrate_local(replays, "*.sdfz", apply=True, log=quiet)
    assert (again.flat, again.moved) == (0, 0)


def test_local_migration_keeps_a_file_that_differs(tmp_path):
    replays = flat_replays(tmp_path)
    (replays / "date=2026-11-01").mkdir()
    (replays / partitioned_name(FIRST)).write_bytes(FIRST.encode())  # the same: flat one goes
    (replays / "date=2026-11-02").mkdir()
    (replays / partitioned_name(SECOND)).write_bytes(b"another file")  # different: both stay
    summary = migrate_local(replays, "*.sdfz", apply=True, log=quiet)
    assert (summary.moved, summary.already_there, summary.deleted) == (1, 1, 1)
    assert summary.left == [SECOND]
    assert not (replays / FIRST).exists()
    assert (replays / SECOND).read_bytes() == SECOND.encode()
    assert (replays / partitioned_name(SECOND)).read_bytes() == b"another file"


def put(bucket, relative_path, data):
    bucket.client.put_object(Bucket=bucket.name, Key=bucket.key(relative_path), Body=data)


def bucket_keys(bucket):
    return sorted(bucket.list_files("replays"))


def test_bucket_dry_run_changes_nothing(bucket):
    for name in (FIRST, SECOND):
        put(bucket, f"replays/{name}", name.encode())
    summary = migrate_bucket(bucket, "replays", "*.sdfz", delete_old=True, log=quiet)
    assert (summary.flat, summary.moved, summary.deleted) == (2, 2, 2)
    assert bucket_keys(bucket) == [FIRST, SECOND]


def test_bucket_migration_copies_verifies_and_keeps_the_old_keys(bucket):
    for name in (FIRST, SECOND, UNDATED):
        put(bucket, f"replays/{name}", name.encode())
    put(bucket, "replays/manifest.parquet", b"manifest")
    summary = migrate_bucket(bucket, "replays", "*.sdfz", apply=True, jobs=2, log=quiet)
    assert (summary.moved, summary.deleted, summary.left) == (3, 0, [])
    assert bucket_keys(bucket) == sorted(
        [
            FIRST,
            SECOND,
            UNDATED,
            "manifest.parquet",
            partitioned_name(FIRST),
            partitioned_name(SECOND),
            partitioned_name(UNDATED),
        ]
    )
    assert bucket.read(f"replays/{partitioned_name(FIRST)}") == FIRST.encode()


def test_bucket_migration_deletes_old_keys_only_after_verifying(bucket, tmp_path):
    for name in (FIRST, SECOND):
        put(bucket, f"replays/{name}", name.encode())
    put(bucket, f"replays/{partitioned_name(SECOND)}", b"another size")
    put(bucket, "replays/manifest.parquet", b"manifest")
    summary = migrate_bucket(bucket, "replays", "*.sdfz", apply=True, delete_old=True, log=quiet)
    assert (summary.moved, summary.deleted, summary.left) == (1, 1, [SECOND])
    assert bucket_keys(bucket) == sorted(
        [SECOND, "manifest.parquet", partitioned_name(FIRST), partitioned_name(SECOND)]
    )

    # once the conflict is gone, a second run finishes the job
    put(bucket, f"replays/{partitioned_name(SECOND)}", SECOND.encode())
    again = migrate_bucket(bucket, "replays", "*.sdfz", apply=True, delete_old=True, log=quiet)
    assert (again.moved, again.already_there, again.deleted, again.left) == (0, 1, 1, [])
    assert bucket_keys(bucket) == sorted(
        ["manifest.parquet", partitioned_name(FIRST), partitioned_name(SECOND)]
    )
    # and the bucket can be synced again
    assert sync_area(bucket, "replays", PULL, data_directory=tmp_path, log=quiet).copied == 2


def test_bucket_migration_reports_a_copy_that_failed(bucket, monkeypatch):
    put(bucket, f"replays/{FIRST}", FIRST.encode())
    monkeypatch.setattr(bucket, "copy", lambda source, destination: None)
    summary = migrate_bucket(bucket, "replays", "*.sdfz", apply=True, delete_old=True, log=quiet)
    assert (summary.deleted, summary.left) == (0, [FIRST])
    assert bucket_keys(bucket) == [FIRST]


def test_cli_migrate_layout(bucket, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REASON8_DATA_DIR", str(tmp_path))
    replays = flat_replays(tmp_path)
    (tmp_path / "parsed").mkdir()
    (tmp_path / "parsed" / "2026-11-01_x.json.zst").write_bytes(b"parsed")

    assert cli.main(["storage", "migrate-layout", "local"]) == 0
    assert "replays: 3 outside the partitions: 3 to move" in capsys.readouterr().err
    assert (replays / FIRST).exists()
    assert cli.main(["storage", "migrate-layout", "local", "--apply"]) == 0
    assert "parsed: 1 outside the partitions: 1 moved" in capsys.readouterr().err
    assert (tmp_path / "parsed" / "date=2026-11-01" / "2026-11-01_x.json.zst").exists()
    assert (replays / partitioned_name(FIRST)).exists()

    uri = f"s3://{bucket.name}/{bucket.prefix}"
    put(bucket, f"replays/{FIRST}", b"old")
    arguments = ["storage", "migrate-layout", "s3", "replays", "--s3-uri", uri]
    assert cli.main([*arguments, "--apply", "--delete-old"]) == 0
    assert "replays: 1 outside the partitions: 1 copied" in capsys.readouterr().err
    assert bucket_keys(bucket) == [partitioned_name(FIRST)]
    assert cli.main(["storage", "migrate-layout", "local", "--delete-old"]) == 2
    assert cli.main(["storage", "migrate-layout", "local", "matches"]) == 2
