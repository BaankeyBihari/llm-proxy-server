"""Unit tests for the AWS ignition Lambda, boto3 mocked via unittest.mock
(stdlib — no moto/localstack dependency; see HLD Key Design Decisions)."""
from unittest.mock import MagicMock, patch

import pytest

from ignition.handler import lambda_handler


def _event(size=None):
    return {"queryStringParameters": {"size": size} if size else {}}


@pytest.fixture(autouse=True)
def instance_id_env(monkeypatch):
    monkeypatch.setenv("INSTANCE_ID", "i-0test1234")


# @spec IGNITE-001, IGNITE-002
@pytest.mark.parametrize(
    "bad_size", ["t3.large", "t4g.nano", "not-a-size", "t4g.small", "t3.small"]
)
def test_rejects_size_outside_whitelist(bad_size):
    with patch("ignition.handler.boto3.client") as mock_client:
        response = lambda_handler(_event(bad_size), None)

    assert response["statusCode"] == 400
    mock_client.return_value.start_instances.assert_not_called()


# @spec IGNITE-001
@pytest.mark.parametrize("good_size", ["t4g.medium", "t3.medium"])
def test_accepts_whitelisted_sizes(good_size):
    with patch("ignition.handler.boto3.client") as mock_client:
        response = lambda_handler(_event(good_size), None)

    assert response["statusCode"] == 200
    mock_client.return_value.start_instances.assert_called_once_with(
        InstanceIds=["i-0test1234"]
    )


# @spec IGNITE-003
def test_defaults_to_t4g_medium_when_size_omitted():
    with patch("ignition.handler.boto3.client") as mock_client:
        response = lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    mock_client.return_value.modify_instance_attribute.assert_called_once_with(
        InstanceId="i-0test1234", InstanceType={"Value": "t4g.medium"}
    )


# @spec IGNITE-004
def test_attempts_resize_before_start_for_valid_size():
    with patch("ignition.handler.boto3.client") as mock_client:
        ec2 = mock_client.return_value
        manager = MagicMock()
        manager.attach_mock(ec2.modify_instance_attribute, "resize")
        manager.attach_mock(ec2.start_instances, "start")

        lambda_handler(_event("t3.medium"), None)

        assert [c[0] for c in manager.mock_calls] == ["resize", "start"]


# @spec IGNITE-005
def test_starts_instance_even_when_resize_raises():
    with patch("ignition.handler.boto3.client") as mock_client:
        ec2 = mock_client.return_value
        ec2.modify_instance_attribute.side_effect = Exception("already running")

        response = lambda_handler(_event("t4g.medium"), None)

    assert response["statusCode"] == 200
    ec2.start_instances.assert_called_once_with(InstanceIds=["i-0test1234"])


# @spec IGNITE-006
def test_always_starts_instance_for_valid_request():
    with patch("ignition.handler.boto3.client") as mock_client:
        lambda_handler(_event(), None)
        mock_client.return_value.start_instances.assert_called_once()


# @spec IGNITE-007
def test_response_body_describes_outcome():
    with patch("ignition.handler.boto3.client"):
        response = lambda_handler(_event("t3.medium"), None)

    assert response["statusCode"] == 200
    assert "t3.medium" in response["body"]
