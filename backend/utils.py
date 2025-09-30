import json
import boto3
from config import AWS_REGION, EMBEDDING_MODEL_ID

bedrock = boto3.client('bedrock-runtime', region_name = AWS_REGION)

def create_embedding(text):
    response = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({"inputText": text})
    )

    result = json.loads(response['body'].read())
    return result['embedding']