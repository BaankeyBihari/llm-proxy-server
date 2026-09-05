"""AWS Lambda "ignition switch": starts the EC2 gateway host on demand,
optionally resizing it first. See docs/intent/aws-ignition/.

Deployed with a Function URL; INSTANCE_ID and the target AWS region are
supplied via Lambda environment variables at deploy time.
"""
import os

import boto3

# @spec IGNITE-001
ALLOWED_SIZES = ["t4g.medium", "t3.medium"]
DEFAULT_SIZE = "t4g.medium"


# @spec IGNITE-001, IGNITE-002, IGNITE-003, IGNITE-004, IGNITE-005, IGNITE-006, IGNITE-007
def lambda_handler(event, context):
    ec2 = boto3.client("ec2", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    instance_id = os.environ["INSTANCE_ID"]

    query_params = event.get("queryStringParameters") or {}
    target_size = query_params.get("size", DEFAULT_SIZE)

    if target_size not in ALLOWED_SIZES:
        return {
            "statusCode": 400,
            "body": f"Error: Invalid size '{target_size}'. Allowed sizes: {', '.join(ALLOWED_SIZES)}",
        }

    try:
        ec2.modify_instance_attribute(
            InstanceId=instance_id, InstanceType={"Value": target_size}
        )
        scale_msg = f"Scaled to {target_size}. "
    except Exception:
        # Expected when the instance is already running, or the resize
        # crosses the t3/t4g architecture boundary — not a request failure.
        scale_msg = "Size unchanged (running or incompatible architecture). "

    ec2.start_instances(InstanceIds=[instance_id])

    return {
        "statusCode": 200,
        "body": f"LiteLLM Ignition Sequence Engaged! {scale_msg}Booting...",
    }
