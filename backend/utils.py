import json
import boto3
from config import AWS_REGION, EMBEDDING_MODEL_ID, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

bedrock = boto3.client(
    'bedrock-runtime',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def create_embedding(text):
    """Generate an embedding for a given text using AWS Titan Embed model."""
    response = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({"inputText": text})
    )
    result = json.loads(response['body'].read())
    return result['embedding']
