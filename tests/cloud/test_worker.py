"""Tests for the cloud worker with a fake queue and a fake engine (no AWS, no games)."""

import json
import threading
from pathlib import Path

import boto3
from botocore.stub import Stubber

from reason8 import cli
from reason8.cloud import worker
from reason8.cloud.messages import BatchSettings, GameMessage
from reason8.cloud.worker import ReceivedMessage, ReplayRunner, Worker


def game(day: int, out_area: str = "state") -> GameMessage:
    return GameMessage(
        f"date=2026-11-0{day}/2026-11-0{day}_10-00-00-000_Map_2026.09.03.sdfz",
        BatchSettings(out_area=out_area),
    )


class FakeQueue:
    def __init__(self, messages):
        self.waiting = [
            ReceivedMessage(body=body, receipt=f"receipt-{index}")
            for index, body in enumerate(messages)
        ]
        self.deleted = []
        self.hidden = []
        self.lock = threading.Lock()

    def receive(self, count, wait_seconds):
        with self.lock:
            taken, self.waiting = self.waiting[:count], self.waiting[count:]
        return taken

    def delete(self, receipt):
        self.deleted.append(receipt)

    def hide(self, receipt, seconds):
        self.hidden.append((receipt, seconds))


class FakeRunner:
    def __init__(self, failing=()):
        self.failing = set(failing)
        self.played = []
        self.failures = []

    def play(self, message):
        self.played.append(message.replay)
        if message.replay in self.failing:
            raise RuntimeError("engine crashed")
        return {"target": message.replay_name, "ok": True}

    def record_failure(self, message, result, attempt):
        self.failures.append((message.replay, result["ok"], attempt))


def run_worker(queue, runner, engines=2):
    Worker(queue, runner, engines=engines, idle_seconds=0, wait_seconds=0).run()


def test_played_games_are_deleted_and_failed_ones_come_back_soon():
    games = [game(day) for day in (1, 2, 3)]
    queue = FakeQueue([message.to_json() for message in games] + ["not a game"])
    runner = FakeRunner(failing=[games[1].replay])

    run_worker(queue, runner)

    assert sorted(runner.played) == sorted(message.replay for message in games)
    assert sorted(queue.deleted) == ["receipt-0", "receipt-2"]
    # the failed game is not deleted: it shows up again and, after three tries, is dead-lettered
    assert queue.hidden == [("receipt-1", worker.RETRY_SECONDS)]
    assert runner.failures == [(games[1].replay, False, 1)]


def test_an_empty_queue_stops_the_worker_at_once_when_idle_time_is_zero():
    runner = FakeRunner()
    run_worker(FakeQueue([]), runner)
    assert runner.played == []


def test_the_worker_waits_for_its_running_games_before_it_stops():
    started = threading.Event()
    release = threading.Event()

    class SlowRunner(FakeRunner):
        def play(self, message):
            started.set()
            release.wait(5)
            return super().play(message)

    queue = FakeQueue([game(1).to_json()])
    runner = SlowRunner()
    thread = threading.Thread(target=run_worker, args=(queue, runner))
    thread.start()
    assert started.wait(5)
    thread.join(0.2)
    assert thread.is_alive()  # idle time is zero, but a game is still running
    release.set()
    thread.join(5)
    assert not thread.is_alive() and queue.deleted == ["receipt-0"]


def test_the_heartbeat_keeps_running_games_hidden():
    release = threading.Event()

    class SlowRunner(FakeRunner):
        def play(self, message):
            release.wait(5)
            return super().play(message)

    queue = FakeQueue([game(1).to_json()])
    worker_under_test = Worker(
        queue, SlowRunner(), engines=1, idle_seconds=0, wait_seconds=0, heartbeat_seconds=0.01
    )
    thread = threading.Thread(target=worker_under_test.run)
    thread.start()
    while not queue.hidden:
        threading.Event().wait(0.01)
    release.set()
    thread.join(5)
    assert queue.hidden[0] == ("receipt-0", worker.VISIBILITY_SECONDS)


def test_the_runner_uploads_the_state_and_tables_with_the_game_table_last(
    bucket, tmp_path, monkeypatch
):
    message = game(1, out_area="state-v7")
    bucket.write(message.replay_path, b"replay")
    uploaded = []
    upload = bucket.upload
    monkeypatch.setattr(
        bucket, "upload", lambda path, key: (uploaded.append(key), upload(path, key))
    )
    monkeypatch.setattr(worker.batch, "fetch_content", lambda data_dir, replay: [])

    def fake_play(replay, target, options):
        assert replay.read_bytes() == b"replay"
        assert options.data_dir == tmp_path / "bar"
        target.write_bytes(b"state")
        stem = target.name.removesuffix(".jsonl.gz")
        for table in ("game", "units"):
            target.with_name(f"{stem}.{table}.parquet").write_bytes(table.encode())
        return {"target": replay.name, "ok": True}

    monkeypatch.setattr(worker.batch, "play", fake_play)
    result = ReplayRunner(bucket, tmp_path, "i-test").play(message)

    assert result["ok"]
    area = "state-v7/date=2026-11-01/"
    stem = Path(message.replay_name).stem
    assert uploaded == [
        f"{area}{stem}.jsonl.gz",
        f"{area}{stem}.units.parquet",
        f"{area}{stem}.game.parquet",
    ]
    assert bucket.read(message.result_path) == b"game"
    # nothing of the game is left on the instance's disk
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_the_runner_reports_a_missing_replay_and_records_failures(bucket, tmp_path):
    message = game(2)
    runner = ReplayRunner(bucket, tmp_path, "i-test")
    result = runner.play(message)
    assert not result["ok"] and "not in the bucket" in result["error"]
    runner.record_failure(message, result, attempt=3)
    record = json.loads(bucket.read(message.failure_path))
    assert (record["attempt"], record["instance"], record["replay"]) == (
        3,
        "i-test",
        message.replay,
    )


def test_an_idle_worker_uploads_its_log_and_terminates_its_instance(bucket, tmp_path, monkeypatch):
    terminated = []
    monkeypatch.setattr(worker, "SqsQueue", lambda url: FakeQueue([]))
    monkeypatch.setattr(worker, "instance_metadata", lambda path: "i-0123")
    monkeypatch.setattr(worker, "terminate_instance", terminated.append)
    uri = f"s3://{bucket.name}/{bucket.prefix}"
    arguments = ["cloud", "worker", "--s3-uri", uri, "--queue-url", "https://queue"]
    arguments += ["--work-dir", str(tmp_path), "--idle-minutes", "0"]

    assert cli.main(arguments) == 0

    assert terminated == ["i-0123"]
    assert b"stopping" in bucket.read("cloud/logs/i-0123/worker.log")


def test_the_sqs_queue_asks_for_the_receive_count_and_extends_visibility():
    client = boto3.client(
        "sqs",
        region_name="eu-central-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    url = "https://sqs.eu-central-1.amazonaws.com/000000000000/games"
    with Stubber(client) as stubber:
        stubber.add_response(
            "receive_message",
            {
                "Messages": [
                    {
                        "Body": "{}",
                        "ReceiptHandle": "r",
                        "Attributes": {"ApproximateReceiveCount": "2"},
                    }
                ]
            },
            {
                "QueueUrl": url,
                "MaxNumberOfMessages": 3,
                "WaitTimeSeconds": 20,
                "VisibilityTimeout": worker.VISIBILITY_SECONDS,
                "MessageSystemAttributeNames": ["ApproximateReceiveCount"],
            },
        )
        stubber.add_response(
            "change_message_visibility",
            {},
            {"QueueUrl": url, "ReceiptHandle": "r", "VisibilityTimeout": 60},
        )
        stubber.add_response("delete_message", {}, {"QueueUrl": url, "ReceiptHandle": "r"})
        queue = worker.SqsQueue(url, client)
        assert queue.receive(3, 20) == [ReceivedMessage("{}", "r", 2)]
        queue.hide("r", 60)
        queue.delete("r")
        stubber.assert_no_pending_responses()
