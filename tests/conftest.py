import boto3
import pytest
from moto import mock_aws

from reason8.bucket import Bucket

BUCKET_NAME = "reason8-test"
REGION = "eu-central-1"


@pytest.fixture
def bucket(monkeypatch, tmp_path):
    """An empty bucket in moto's in-memory S3, as ``s3://reason8-test/shared/``."""
    # never touch real credentials or configuration
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("REASON8_S3_URI", raising=False)
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(
            Bucket=BUCKET_NAME, CreateBucketConfiguration={"LocationConstraint": REGION}
        )
        yield Bucket(f"s3://{BUCKET_NAME}/shared", client)
