import boto3
import os

def lambda_handler(event, context):
    ec2 = boto3.client('ec2', region_name='us-east-1') # Change to your region
    instance_id = 'i-0abcd1234efgh5678' # Your instance ID
    
    # 1. Strict Whitelist: Only allow small and medium sizes
    ALLOWED_SIZES = ['small', 'medium']
    
    # Check query parameters for requested size (default to small)
    query_params = event.get('queryStringParameters', {}) or {}
    target_size = query_params.get('size', 'small')
    
    if target_size not in ALLOWED_SIZES:
        return {
            "statusCode": 400,
            "body": f"Error: Invalid size '{target_size}'. Allowed sizes are: {', '.join(ALLOWED_SIZES)}"
        }
    
    # Prefix the size with the instance family (t4g)
    target_instance_type = f"t4g.{target_size}"

    # 2. Change the instance type 
    try:
        ec2.modify_instance_attribute(
            InstanceId=instance_id,
            InstanceType={'Value': target_instance_type}
        )
        scale_msg = f"Successfully configured instance to {target_instance_type}"
        print(scale_msg)
    except Exception as e:
        # If the instance is running this throws an error we safely ignore
        scale_msg = f"Size unchanged (instance is running). Error: {e}"
        print(scale_msg)

    # 3. Start the instance
    ec2.start_instances(InstanceIds=[instance_id])
    
    return {
        "statusCode": 200, 
        "body": f"LiteLLM Server Booting Up! {scale_msg}"
    }