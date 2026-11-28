# Re-simulating in the cloud

The commands that play a batch of replays on EC2 spot instances instead of the
local machines, and where their data goes. Why it is built this way:
[ADR 0020](../decisions/0020-re-simulate-in-bulk-on-spot-instances.md). The
replays come from the private bucket of
[ADR 0016](../decisions/0016-download-and-store-the-data.md), and the results
go back to it.

## Before the first run

- AWS credentials of the account that owns the bucket, configured as usual
  (`aws configure` or `aws login`); the region is the configuration's, the
  bucket's own region.
- `REASON8_S3_URI` (or `--s3-uri`) naming the bucket, as for `reason8 sync`.
- The replays of the batch in the bucket: `reason8 sync push replays`.
- The commit to run pushed to `origin`: the instances clone it from there.
- A spot vCPU quota for the instances: `reason8 cloud up` prints how many
  instances it allows. Ten m7a.2xlarge need 80 vCPUs of "All Standard (A, C,
  D, H, I, M, R, T, Z) Spot Instance Requests"; more is asked for in Service
  Quotas.

## A run

```mermaid
sequenceDiagram
    actor Person
    participant Commands as reason8 cloud
    participant Stack as CloudFormation stack
    participant Queue as SQS queue
    participant Group as Auto Scaling group
    participant Worker as worker on an instance
    participant Bucket as S3 bucket
    Person->>Commands: up
    Commands->>Stack: create or update, pinned commit
    Person->>Commands: run --list FILE --instances 10
    Commands->>Bucket: which games are done, which replays are there
    Commands->>Queue: one message per game
    Commands->>Group: desired capacity
    Group->>Worker: start spot instances, cloud-init setup
    loop while the queue has games, one per free engine
        Worker->>Queue: take a game, keep it hidden while it plays
        Worker->>Bucket: get the replay
        Worker->>Worker: fetch engine, game, map; play the replay
        Worker->>Bucket: state file and tables, the game table last
        Worker->>Queue: delete the message
    end
    Worker->>Bucket: its log
    Worker->>Group: terminate itself, shrink the group by one
    Person->>Commands: status
    Person->>Commands: sync pull state
```

```sh
export REASON8_S3_URI=s3://<bucket>
uv run reason8 cloud up                     # once, and after each code change
uv run reason8 cloud run --list data/workers/context.txt --instances 10 \
    --max-frame 36000 --out-area state-v7
uv run reason8 cloud status                 # as often as you like
uv run reason8 sync pull state-v7           # the results, into data/state-v7
uv run reason8 cloud down                   # stop early; --purge, --delete
```

Each command prints its own details with `--help`.

`cloud up`
: Creates or updates the stack (`reason8/cloud/stack.yaml`) in the default
  VPC: the queue and its dead-letter queue, the workers' role, the launch
  template and the group. Pins the commit the instances run (HEAD by default,
  which origin must have), waits until the stack is done, prints its outputs,
  the spot quota and how many instances it allows. Options: `--max-instances`
  (the group's cap, 10), `--instance-types` (spot types of the same shape, the
  default first: m7a.2xlarge, m7i.2xlarge, m6a.2xlarge, m6i.2xlarge),
  `--engines` (games per instance, 5), `--idle-minutes` (5), `--volume-gib`
  (100), `--commit`.

`cloud run`
: Queues the games of a list (the format `reason8 headless list` writes and
  `reason8 headless batch --list` reads; only the file names count), without
  the games whose results are already in `--out-area` and those whose replay
  is not in the bucket. Records the batch in `cloud/batches/` and sets the
  group's desired capacity to the smallest of `--instances`, the cap, what the
  spot quota allows and the instances the games keep busy. Also `--max-frame`,
  `--timeout`, `--set KEY=VALUE` as for a local batch, and `--dry-run`.

`cloud status`
: Games waiting, in flight and dead-lettered; the group's instances; for the
  latest batch the games with results, the instance hours since it started and
  a rough cost at the current spot prices.

`cloud down`
: Sets the desired capacity to 0; the games being played go back to the queue.
  `--purge` also empties the queue, `--delete` deletes the stack. Nothing in
  the bucket is deleted.

`cloud worker`
: What runs on each instance as the systemd service `reason8-worker`; not run
  by hand.

## In the bucket

Paths relative to the bucket's location (`REASON8_S3_URI`):

`state/date=DAY/NAME.jsonl.gz`, `state/date=DAY/NAME.TABLE.parquet`
: The results, as a local batch writes them to `data/state`. With
  `--out-area state-<name>` they go to `state-<name>/` instead, for a state
  format of its own; `reason8 sync pull state-<name>` brings them to
  `data/state-<name>`.

`cloud/failures/AREA/date=DAY/NAME.json`
: The latest failed try of a game: the engine run's result, the try's number
  and the instance.

`cloud/logs/INSTANCE/`
: `worker.log` (uploaded after every game and before the instance ends);
  `setup.log` and, when the worker failed, `journal.log`.

`cloud/batches/TIME.json`
: Each batch: its list's name, out area, settings and games.

## When something goes wrong

- A game in the dead-letter queue failed three times (or its instance was
  reclaimed three times). Its failure record says why; desyncs and missing
  content are reported as by `reason8 headless batch`. After a fix, queue the
  list again: games with results are left out.
- An instance whose setup or worker failed uploads `setup.log` and
  `journal.log` and terminates itself, so the group shrinks.
- A running instance can be looked into with Session Manager
  (`aws ssm start-session --target INSTANCE`), then
  `journalctl -u reason8-worker`.
- `cloud status` shows instances but no games in flight: they may still be
  setting up (a few minutes) or fetching content.
