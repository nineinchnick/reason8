from datetime import datetime, timedelta

import httpx
import polars as pl
import pytest
from botocore.exceptions import ClientError

from reason8.data.download import (
    ERROR,
    FROM_BAR,
    FROM_BUCKET,
    MANIFEST_NAME,
    MISSING,
    OK,
    USER_AGENT,
    RateLimiter,
    download_order,
    download_replays,
    make_client,
    read_manifest,
)

START = datetime(2026, 6, 1)
MAPS = ("Supreme Isthmus v2.1", "All That Glitters v2.2.3", "Rosetta 1.4.4")


def selection(count_per_map=(4, 4, 1)):
    rows = []
    match_id = 0
    for map_name, count in zip(MAPS, count_per_map, strict=True):
        for _ in range(count):
            match_id += 1
            rows.append(
                {
                    "match_id": match_id,
                    "replay_file_name": f"{match_id:03d}_{map_name}.sdfz",
                    "map": map_name,
                    "start_time": START + timedelta(hours=match_id),
                    "engine": "2026.09.03",
                    "game_version": "Beyond All Reason test-1",
                }
            )
    return pl.DataFrame(rows)


class FakeServer:
    """Serves replays by file name; answers listed in ``statuses`` override the default 200."""

    def __init__(self, statuses=None):
        self.statuses = statuses or {}
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        file_name = request.url.path.rsplit("/", 1)[-1]
        status = self.statuses.get(file_name, 200)
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, content=b"replay " + file_name.encode())


def run_download(tmp_path, server, queue, limit, **options):
    with make_client(httpx.MockTransport(server)) as client:
        return download_replays(
            queue,
            limit,
            dest=tmp_path,
            client=client,
            limiter=RateLimiter(0),
            log=lambda line: None,
            **options,
        )


def test_download_order_takes_turns_between_maps():
    queue = download_order(selection((4, 4, 1)), "newest")
    assert queue["map"].to_list() == [
        MAPS[1],
        MAPS[2],
        MAPS[0],
        MAPS[1],
        MAPS[0],
        MAPS[1],
        MAPS[0],
        MAPS[1],
        MAPS[0],
    ]
    isthmus = queue.filter(pl.col("map") == MAPS[0])["start_time"].to_list()
    assert isthmus == sorted(isthmus, reverse=True)


def test_random_order_is_stable_and_nested():
    small = selection((20, 20, 20))
    large = pl.concat([small, selection((20, 20, 20)).with_columns(pl.col("match_id") + 100)])
    first = download_order(small, "random", seed=7)["match_id"].to_list()
    assert first == download_order(small, "random", seed=7)["match_id"].to_list()
    assert first != download_order(small, "random", seed=8)["match_id"].to_list()
    assert sorted(first) != first
    # new matches (a newer dump) are inserted; the others keep their order within each map
    in_large = download_order(large, "random", seed=7)
    for map_name in MAPS:
        before = download_order(small, "random", seed=7).filter(pl.col("map") == map_name)
        after = in_large.filter(pl.col("map") == map_name, pl.col("match_id") < 100)
        assert after["match_id"].to_list() == before["match_id"].to_list()


def test_download_order_rejects_unknown_order():
    with pytest.raises(ValueError):
        download_order(selection(), "oldest")


def test_downloads_until_limit_and_records_manifest(tmp_path):
    server = FakeServer()
    queue = download_order(selection(), "newest")
    summary = run_download(tmp_path, server, queue, 3)

    assert summary.on_disk == 3
    assert summary.requests == 3
    files = sorted(path.name for path in tmp_path.glob("*.sdfz"))
    assert files == sorted(queue["replay_file_name"].head(3).to_list())
    assert not list(tmp_path.glob("*.part"))
    assert all(request.headers["User-Agent"] == USER_AGENT for request in server.requests)
    assert "github.com/nineinchnick/reason8" in USER_AGENT
    first_name = queue["replay_file_name"][0]
    assert str(server.requests[0].url).endswith("/BAR/demos/" + first_name.replace(" ", "%20"))

    manifest = read_manifest(tmp_path / MANIFEST_NAME)
    assert {row["status"] for row in manifest.values()} == {OK}
    assert {row["attempts"] for row in manifest.values()} == {1}
    first = manifest[queue["match_id"][0]]
    assert first["bytes"] == (tmp_path / first["replay_file_name"]).stat().st_size
    assert first["engine"] == "2026.09.03"


def test_existing_files_count_and_are_not_requested(tmp_path):
    queue = download_order(selection(), "newest")
    (tmp_path / queue["replay_file_name"][0]).write_bytes(b"already here")
    server = FakeServer()
    summary = run_download(tmp_path, server, queue, 2)

    assert summary.requests == 1
    assert len(server.requests) == 1
    assert (tmp_path / queue["replay_file_name"][0]).read_bytes() == b"already here"
    assert read_manifest(tmp_path / MANIFEST_NAME)[queue["match_id"][0]]["status"] == OK

    # a second run with the same limit asks for nothing
    again = FakeServer()
    assert run_download(tmp_path, again, queue, 2).requests == 0
    assert again.requests == []


def test_missing_replays_are_recorded_skipped_and_replaced(tmp_path):
    queue = download_order(selection(), "newest")
    expired = queue["replay_file_name"][0]
    server = FakeServer({expired: 404})
    summary = run_download(tmp_path, server, queue, 2)

    assert summary.on_disk == 2
    assert summary.requests == 3
    row = read_manifest(tmp_path / MANIFEST_NAME)[queue["match_id"][0]]
    assert (row["status"], row["http_status"], row["attempts"]) == (MISSING, 404, 1)
    assert not (tmp_path / expired).exists()

    again = FakeServer()
    assert run_download(tmp_path, again, queue, 2).requests == 0
    retried = FakeServer()
    assert run_download(tmp_path, retried, queue, 2, retry_missing=True).requests == 1
    assert read_manifest(tmp_path / MANIFEST_NAME)[queue["match_id"][0]]["status"] == OK


def test_errors_are_retried_up_to_max_attempts(tmp_path):
    queue = download_order(selection((1, 0, 0)), "newest")
    file_name = queue["replay_file_name"][0]
    for attempt in range(1, 4):
        server = FakeServer({file_name: 500})
        summary = run_download(tmp_path, server, queue, 1, max_attempts=3)
        assert summary.requests == 1
        row = read_manifest(tmp_path / MANIFEST_NAME)[queue["match_id"][0]]
        assert (row["status"], row["error"], row["attempts"]) == (ERROR, "HTTP 500", attempt)
    assert run_download(tmp_path, FakeServer(), queue, 1, max_attempts=3).requests == 0


def test_slow_down_stops_the_run(tmp_path):
    queue = download_order(selection(), "newest")
    server = FakeServer({queue["replay_file_name"][1]: 429})
    summary = run_download(tmp_path, server, queue, 5)
    assert summary.requests == 2
    assert summary.stopped
    assert len(read_manifest(tmp_path / MANIFEST_NAME)) == 2


def test_broken_connection_leaves_no_partial_file(tmp_path):
    def server(request):
        raise httpx.ReadError("connection reset", request=request)

    queue = download_order(selection((1, 0, 0)), "newest")
    summary = run_download(tmp_path, server, queue, 1)
    assert summary.on_disk == 0
    assert list(tmp_path.glob("*.sdfz*")) == []
    row = read_manifest(tmp_path / MANIFEST_NAME)[queue["match_id"][0]]
    assert row["status"] == ERROR
    assert "ReadError" in row["error"]


def test_incomplete_body_is_an_error(tmp_path):
    def server(request):
        return httpx.Response(200, content=b"short", headers={"Content-Length": "100"})

    queue = download_order(selection((1, 0, 0)), "newest")
    run_download(tmp_path, server, queue, 1)
    assert list(tmp_path.glob("*.sdfz*")) == []
    assert read_manifest(tmp_path / MANIFEST_NAME)[queue["match_id"][0]]["status"] == ERROR


def test_unsafe_file_names_are_not_requested(tmp_path):
    queue = selection((1, 0, 0)).with_columns(replay_file_name=pl.lit("../escape.sdfz"))
    server = FakeServer()
    run_download(tmp_path, server, queue, 1)
    assert server.requests == []
    assert read_manifest(tmp_path / MANIFEST_NAME)[1]["error"] == "unsafe file name"


def test_rate_limiter_spaces_requests():
    now = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(1.0, clock=lambda: now[0], sleep=sleep)
    limiter.wait()
    now[0] += 0.25
    limiter.wait()
    now[0] += 3.0
    limiter.wait()
    assert sleeps == [pytest.approx(0.75)]


class CountingLimiter(RateLimiter):
    def __init__(self):
        super().__init__(0)
        self.waits = 0

    def wait(self):
        self.waits += 1


def test_replays_in_the_bucket_are_copied_without_asking_bar(tmp_path, bucket):
    queue = download_order(selection(), "newest")
    in_bucket = queue["replay_file_name"][0]
    bucket.write(f"replays/{in_bucket}", b"from the bucket")
    server = FakeServer()
    limiter = CountingLimiter()
    with make_client(httpx.MockTransport(server)) as client:
        summary = download_replays(
            queue,
            2,
            dest=tmp_path,
            client=client,
            limiter=limiter,
            bucket=bucket,
            log=lambda line: None,
        )

    assert (summary.on_disk, summary.from_bucket, summary.requests, summary.uploaded) == (
        2,
        1,
        1,
        1,
    )
    assert limiter.waits == 1
    assert [request.url.path.rsplit("/", 1)[-1] for request in server.requests] == [
        queue["replay_file_name"][1]
    ]
    assert (tmp_path / in_bucket).read_bytes() == b"from the bucket"
    from_bar = queue["replay_file_name"][1]
    assert bucket.read(f"replays/{from_bar}") == (tmp_path / from_bar).read_bytes()
    manifest = read_manifest(tmp_path / MANIFEST_NAME)
    first, second = manifest[queue["match_id"][0]], manifest[queue["match_id"][1]]
    assert (first["status"], first["source"], first["attempts"]) == (OK, FROM_BUCKET, 0)
    assert first["bytes"] == len(b"from the bucket")
    assert (second["status"], second["source"], second["attempts"]) == (OK, FROM_BAR, 1)


def test_missing_replays_are_not_uploaded(tmp_path, bucket):
    queue = download_order(selection((1, 0, 0)), "newest")
    file_name = queue["replay_file_name"][0]
    summary = run_download(tmp_path, FakeServer({file_name: 404}), queue, 1, bucket=bucket)
    assert (summary.requests, summary.uploaded) == (1, 0)
    assert bucket.read(f"replays/{file_name}") is None
    row = read_manifest(tmp_path / MANIFEST_NAME)[queue["match_id"][0]]
    assert (row["status"], row["source"]) == (MISSING, FROM_BAR)


def test_a_failed_upload_does_not_stop_the_download(tmp_path, bucket, monkeypatch):
    def refuse(path, relative_path):
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")

    monkeypatch.setattr(bucket, "upload", refuse)
    lines = []
    queue = download_order(selection(), "newest")
    with make_client(httpx.MockTransport(FakeServer())) as client:
        summary = download_replays(
            queue,
            2,
            dest=tmp_path,
            client=client,
            limiter=RateLimiter(0),
            bucket=bucket,
            log=lines.append,
        )
    assert (summary.on_disk, summary.requests, summary.uploaded) == (2, 2, 0)
    assert sum("could not upload" in line for line in lines) == 2
