"""The private S3 bucket that holds the shared copy of the data directory.

S3 is opt-in: nothing uses it unless ``--s3-uri`` or the ``REASON8_S3_URI`` environment variable
names a location, such as ``s3://bucket`` or ``s3://bucket/some/prefix``. Objects are stored
under that location with the same relative paths as in the data directory, date partitions
included (``replays/date=2026-11-01/<replay_file_name>``,
``tables/date=2026-11-01/2026-11-01.games.parquet``, ``matches/<dump>.parquet``, ..., see
`reason8.paths`). Credentials and region come from the usual AWS configuration (``~/.aws``,
``AWS_PROFILE``, ...).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import boto3
from boto3.exceptions import S3UploadFailedError
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import BotoCoreError, ClientError

S3_URI_VARIABLE = "REASON8_S3_URI"
#: Error codes S3 answers with when an object doesn't exist (HEAD requests only get "404").
NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})
#: The classic transfer manager: the CRT one (installed for ``aws login`` credentials) bypasses
#: botocore's HTTP layer, and gains nothing for files of a few megabytes.
TRANSFER_CONFIG = TransferConfig(preferred_transfer_client="classic")
#: What a failed transfer raises: credentials, connection, service and upload errors.
TRANSFER_ERRORS = (BotoCoreError, ClientError, S3UploadFailedError)
#: The most keys one DeleteObjects request takes.
DELETE_BATCH_SIZE = 1000


class Bucket:
    """A location in S3 (a bucket and an optional key prefix) that mirrors the data directory."""

    def __init__(self, uri: str, client: Any | None = None):
        if not uri.startswith("s3://"):
            raise ValueError(f"an S3 location starts with s3://, not {uri!r}")
        name, _, prefix = uri.removeprefix("s3://").partition("/")
        if not name:
            raise ValueError(f"no bucket name in {uri!r}")
        self.name = name
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self.client = client or boto3.client("s3")

    def __repr__(self) -> str:
        return f"Bucket('s3://{self.name}/{self.prefix}')"

    def key(self, relative_path: str) -> str:
        """Object key of a path relative to the data directory, e.g. ``replays/date=.../x.sdfz``."""
        return self.prefix + relative_path

    def list_files(self, directory: str) -> dict[str, int]:
        """Sizes of the objects under ``directory`` at any depth, by path relative to it."""
        directory_prefix = self.key(directory.strip("/") + "/")
        sizes = {}
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.name, Prefix=directory_prefix):
            for listed_object in page.get("Contents", []):
                sizes[listed_object["Key"].removeprefix(directory_prefix)] = listed_object["Size"]
        return sizes

    def download(self, relative_path: str, path: Path) -> bool:
        """Copy an object to ``path``; ``False`` if there is no such object.

        The transfer writes to a temporary file next to ``path`` and renames it when complete.
        """
        try:
            self.client.download_file(
                self.name, self.key(relative_path), str(path), Config=TRANSFER_CONFIG
            )
        except ClientError as error:
            if is_not_found(error):
                return False
            raise
        return True

    def upload(self, path: Path, relative_path: str) -> None:
        self.client.upload_file(
            str(path), self.name, self.key(relative_path), Config=TRANSFER_CONFIG
        )

    def read(self, relative_path: str) -> bytes | None:
        """Contents of a small object, or ``None`` if there is no such object."""
        try:
            response = self.client.get_object(Bucket=self.name, Key=self.key(relative_path))
        except ClientError as error:
            if is_not_found(error):
                return None
            raise
        return response["Body"].read()

    def write(self, relative_path: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.name, Key=self.key(relative_path), Body=data)

    def copy(self, source_path: str, destination_path: str) -> None:
        """Copy an object to another key inside S3, without downloading it."""
        self.client.copy(
            {"Bucket": self.name, "Key": self.key(source_path)},
            self.name,
            self.key(destination_path),
            Config=TRANSFER_CONFIG,
        )

    def delete(self, relative_paths: list[str]) -> None:
        """Delete objects, a thousand per request; raises if any of them could not be deleted."""
        for start in range(0, len(relative_paths), DELETE_BATCH_SIZE):
            batch = relative_paths[start : start + DELETE_BATCH_SIZE]
            response = self.client.delete_objects(
                Bucket=self.name,
                Delete={"Objects": [{"Key": self.key(path)} for path in batch], "Quiet": True},
            )
            if response.get("Errors"):
                raise RuntimeError(f"could not delete from S3: {response['Errors'][:5]}")


def is_not_found(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") in NOT_FOUND_CODES


def configured_bucket(uri: str | None = None) -> Bucket | None:
    """The bucket named by ``uri`` or ``REASON8_S3_URI``; ``None`` when neither is set."""
    uri = uri or os.environ.get(S3_URI_VARIABLE)
    return Bucket(uri) if uri else None


def add_uri_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--s3-uri",
        metavar="URI",
        help=f"shared data in S3, e.g. s3://bucket/prefix (default: ${S3_URI_VARIABLE})",
    )
