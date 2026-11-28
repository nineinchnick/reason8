"""Play the games of the cloud queue on this machine, then terminate it (run on an instance).

    uv run reason8 cloud worker --s3-uri s3://<bucket>/<prefix> --queue-url URL \\
        --engines 5 --idle-minutes 5 --work-dir /srv/reason8/work

The instance's user data starts this as a systemd service (``reason8-worker``, see
``reason8/cloud/stack.yaml``); it is not meant to be run by hand, except with
``--no-terminate`` to try it.

It takes a game from the queue (`reason8.cloud.messages`) whenever one of its ``--engines``
is free, downloads the replay from the bucket, fetches the engine, game and map the replay
needs, plays it like `reason8 headless batch` and uploads the state file and its tables to the
game's out area, the ``game`` table last. Then it deletes the message. While a game runs the
message is kept hidden from the other workers (a heartbeat extends its visibility), and when an
instance is reclaimed the message simply shows up again. A game that fails is logged, a record
of the failure is uploaded to ``cloud/failures/``, and its message comes back after a minute:
after three tries the queue moves it to the dead-letter queue.

When the queue has been empty and no game has run for ``--idle-minutes``, the worker uploads
its log to ``cloud/logs/<instance>/worker.log`` and terminates its own instance through the
Auto Scaling group, which shrinks by one; the last worker leaves the group at 0.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import boto3

from reason8.cloud import content
from reason8.cloud.messages import LOGS_DIRECTORY, GameMessage, MessageError, result_files
from reason8.data import storage
from reason8.data.storage import Bucket
from reason8.headless import batch
from reason8.headless.state import state_path

logger = logging.getLogger("reason8.cloud.worker")

#: How long a received message stays hidden from the other workers; the heartbeat renews it.
VISIBILITY_SECONDS = 900
HEARTBEAT_SECONDS = 300
#: When a failed game's message shows up again for another try.
RETRY_SECONDS = 60
#: SQS long polling: the longest a receive waits for a message.
WAIT_SECONDS = 20
#: The most messages SQS hands out in one receive.
RECEIVE_LIMIT = 10
METADATA_URL = "http://169.254.169.254/latest"


@dataclass(frozen=True)
class ReceivedMessage:
    body: str
    receipt: str
    #: How often the queue has handed it out, this time included.
    receive_count: int = 1


class GameQueue(Protocol):
    def receive(self, count: int, wait_seconds: int) -> list[ReceivedMessage]: ...
    def delete(self, receipt: str) -> None: ...
    def hide(self, receipt: str, seconds: int) -> None: ...


class GameRunner(Protocol):
    def play(self, message: GameMessage) -> dict: ...
    def record_failure(self, message: GameMessage, result: dict, attempt: int) -> None: ...


class SqsQueue:
    """The game queue in SQS."""

    def __init__(self, url: str, client: Any | None = None):
        self.url = url
        self.client = client or boto3.client("sqs")

    def receive(self, count: int, wait_seconds: int) -> list[ReceivedMessage]:
        response = self.client.receive_message(
            QueueUrl=self.url,
            MaxNumberOfMessages=max(1, min(count, RECEIVE_LIMIT)),
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=VISIBILITY_SECONDS,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        return [
            ReceivedMessage(
                body=message["Body"],
                receipt=message["ReceiptHandle"],
                receive_count=int(message.get("Attributes", {}).get("ApproximateReceiveCount", 1)),
            )
            for message in response.get("Messages", [])
        ]

    def delete(self, receipt: str) -> None:
        self.client.delete_message(QueueUrl=self.url, ReceiptHandle=receipt)

    def hide(self, receipt: str, seconds: int) -> None:
        self.client.change_message_visibility(
            QueueUrl=self.url, ReceiptHandle=receipt, VisibilityTimeout=seconds
        )


class Worker:
    """Plays the games of a queue, ``engines`` at a time, until it has been idle long enough."""

    def __init__(
        self,
        queue: GameQueue,
        runner: GameRunner,
        *,
        engines: int,
        idle_seconds: float,
        wait_seconds: int = WAIT_SECONDS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.queue = queue
        self.runner = runner
        self.engines = max(1, engines)
        self.idle_seconds = idle_seconds
        self.wait_seconds = wait_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.clock = clock
        self.running: dict[Future, ReceivedMessage] = {}
        self.running_lock = threading.Lock()
        self.stopped = threading.Event()
        self.played = 0
        self.failed = 0

    def run(self) -> None:
        """Play games until the queue has been empty and nothing ran for ``idle_seconds``."""
        heartbeat = threading.Thread(target=self.keep_hidden, name="heartbeat", daemon=True)
        heartbeat.start()
        idle_since = self.clock()
        try:
            with ThreadPoolExecutor(max_workers=self.engines, thread_name_prefix="game") as pool:
                while True:
                    with self.running_lock:
                        running = list(self.running)
                    free = self.engines - len(running)
                    if free <= 0:
                        wait(running, timeout=self.wait_seconds, return_when=FIRST_COMPLETED)
                        continue
                    received = self.receive(free)
                    for message in received:
                        future = pool.submit(self.handle, message)
                        with self.running_lock:
                            self.running[future] = message
                        future.add_done_callback(self.finished)
                    if received or running:
                        idle_since = self.clock()
                    elif self.clock() - idle_since >= self.idle_seconds:
                        logger.info(
                            "idle for %.0f s after %d games (%d failed): stopping",
                            self.clock() - idle_since,
                            self.played,
                            self.failed,
                        )
                        return
        finally:
            self.stopped.set()

    def receive(self, count: int) -> list[ReceivedMessage]:
        try:
            return self.queue.receive(count, self.wait_seconds)
        except Exception:
            logger.exception("could not receive from the queue")
            time.sleep(min(self.wait_seconds, 5))
            return []

    def finished(self, future: Future) -> None:
        with self.running_lock:
            self.running.pop(future, None)

    def keep_hidden(self) -> None:
        """Extend the visibility of the messages of the running games, so that no other worker
        gets them while they are played."""
        while not self.stopped.wait(self.heartbeat_seconds):
            with self.running_lock:
                receipts = [message.receipt for message in self.running.values()]
            for receipt in receipts:
                try:
                    self.queue.hide(receipt, VISIBILITY_SECONDS)
                except Exception:
                    logger.exception("could not extend a message's visibility")

    def handle(self, received: ReceivedMessage) -> None:
        try:
            message = GameMessage.from_json(received.body)
        except MessageError:
            # left alone: it goes to the dead-letter queue after three tries
            logger.exception("not a game message")
            return
        try:
            result = self.runner.play(message)
        except (Exception, SystemExit) as error:
            logger.exception("%s failed", message.replay)
            result = {"target": message.replay_name, "ok": False, "error": repr(error)}
        logger.info("%s", json.dumps({**result, "attempt": received.receive_count}))
        if result.get("ok"):
            self.played += 1
            try:
                self.queue.delete(received.receipt)
            except Exception:
                # the game comes back and is played again; its result is the same
                logger.exception("could not delete the message of %s", message.replay)
            return
        self.failed += 1
        try:
            self.runner.record_failure(message, result, received.receive_count)
        except Exception:
            logger.exception("could not record the failure of %s", message.replay)
        try:
            self.queue.hide(received.receipt, RETRY_SECONDS)
        except Exception:
            logger.exception("could not hand %s back to the queue", message.replay)


class ReplayRunner:
    """Plays the game of a message on this machine and uploads its results to the bucket."""

    def __init__(self, bucket: Bucket, work_dir: Path, instance_id: str):
        self.bucket = bucket
        self.work_dir = work_dir
        #: The engines, game versions and maps (`reason8 headless setup`).
        self.data_dir = work_dir / "bar"
        self.instance_id = instance_id
        # the downloads share one data dir, so they go one at a time (as in a batch)
        self.fetch_lock = threading.Lock()

    def play(self, message: GameMessage) -> dict:
        replay = self.work_dir / "replays" / message.replay
        replay.parent.mkdir(parents=True, exist_ok=True)
        target = state_path(self.work_dir / message.batch.out_area, replay)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if not self.bucket.download(message.replay_path, replay):
                return {"target": replay.name, "ok": False, "error": "replay not in the bucket"}
            with self.fetch_lock:
                missing = batch.fetch_content(self.data_dir, replay)
            if missing:
                return {"target": replay.name, "ok": False, "missing": missing}
            options = batch.PlayOptions(
                data_dir=self.data_dir,
                max_frame=message.batch.max_frame,
                snapshot_seconds=message.batch.snapshot_seconds,
                timeout=message.batch.timeout,
                settings=message.batch.settings,
            )
            result = batch.play(replay, target, options)
            if result["ok"]:
                self.upload_results(message, target)
            return result
        finally:
            replay.unlink(missing_ok=True)
            for path in result_files(target):
                path.unlink(missing_ok=True)

    def upload_results(self, message: GameMessage, state_file: Path) -> None:
        area = self.work_dir / message.batch.out_area
        for path in result_files(state_file):
            relative_path = path.relative_to(area).as_posix()
            self.bucket.upload(path, f"{message.batch.out_area}/{relative_path}")

    def record_failure(self, message: GameMessage, result: dict, attempt: int) -> None:
        record = {
            "replay": message.replay,
            "attempt": attempt,
            "instance": self.instance_id,
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "result": result,
        }
        self.bucket.write(message.failure_path, json.dumps(record, indent=1).encode())


def instance_metadata(path: str, timeout: float = 5) -> str:
    """One value of this instance's metadata, through IMDSv2."""
    token_request = urllib.request.Request(
        f"{METADATA_URL}/api/token",
        method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "300"},
    )
    with urllib.request.urlopen(token_request, timeout=timeout) as response:
        token = response.read().decode()
    request = urllib.request.Request(
        f"{METADATA_URL}/meta-data/{path}", headers={"X-aws-ec2-metadata-token": token}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode()


def terminate_instance(instance_id: str, client: Any | None = None) -> None:
    """Terminate this instance and shrink its Auto Scaling group by one."""
    client = client or boto3.client("autoscaling")
    client.terminate_instance_in_auto_scaling_group(
        InstanceId=instance_id, ShouldDecrementDesiredCapacity=True
    )


def upload_log(bucket: Bucket, log_file: Path, instance_id: str) -> None:
    try:
        bucket.upload(log_file, f"{LOGS_DIRECTORY}/{instance_id}/worker.log")
    except storage.TRANSFER_ERRORS:
        logger.exception("could not upload the log")


class LoggingRunner:
    """A runner that uploads the worker's log after every game, so that the log of an instance
    is in the bucket even when the instance is reclaimed."""

    def __init__(self, runner: ReplayRunner, log_file: Path):
        self.runner = runner
        self.log_file = log_file

    def play(self, message: GameMessage) -> dict:
        try:
            return self.runner.play(message)
        finally:
            upload_log(self.runner.bucket, self.log_file, self.runner.instance_id)

    def record_failure(self, message: GameMessage, result: dict, attempt: int) -> None:
        self.runner.record_failure(message, result, attempt)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    storage.add_uri_argument(parser)
    parser.add_argument("--queue-url", required=True, help="the game queue (SQS)")
    parser.add_argument("--engines", type=int, default=5, help="games at once")
    parser.add_argument(
        "--idle-minutes",
        type=float,
        default=5,
        help="stop when the queue was empty this long (default 5)",
    )
    parser.add_argument(
        "--work-dir", type=Path, required=True, help="engines, games, maps and the games at work"
    )
    parser.add_argument(
        "--no-terminate",
        action="store_true",
        help="only stop when idle, do not terminate the instance",
    )


def run(args: argparse.Namespace) -> int:
    bucket = storage.configured_bucket(args.s3_uri)
    if bucket is None:
        print(f"no S3 location: pass --s3-uri or set {storage.S3_URI_VARIABLE}", file=sys.stderr)
        return 2
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    log_file = work_dir / "worker.log"
    handlers = [logging.StreamHandler(sys.stderr), logging.FileHandler(log_file)]
    for handler in handlers:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        return work(args, bucket, work_dir, log_file)
    finally:
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()


def work(args: argparse.Namespace, bucket: Bucket, work_dir: Path, log_file: Path) -> int:
    try:
        instance_id = instance_metadata("instance-id")
    except OSError:
        if not args.no_terminate:
            raise
        instance_id = "local"
    logger.info("worker on %s, %d engines, queue %s", instance_id, args.engines, args.queue_url)
    runner = ReplayRunner(bucket, work_dir, instance_id)
    try:
        if content.restore(bucket, runner.data_dir):
            logger.info("engines, game versions and maps unpacked from the bucket")
    except (*storage.TRANSFER_ERRORS, OSError):
        # the games fetch what they need from BAR's servers instead
        logger.exception("could not unpack the content archive")
    worker = Worker(
        SqsQueue(args.queue_url),
        LoggingRunner(runner, log_file),
        engines=args.engines,
        idle_seconds=args.idle_minutes * 60,
    )
    worker.run()
    upload_log(bucket, log_file, instance_id)
    if not args.no_terminate:
        logger.info("terminating %s", instance_id)
        terminate_instance(instance_id)
    return 0
