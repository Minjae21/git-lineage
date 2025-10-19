#!/bin/bash

# Variables
FUNCTION_NAME="bedrock-api"
ZIP_FILE="lambda_function.zip"
ROLE_ARN="arn:aws:iam::<ACCOUNT_ID>:role/<BEDROCK_LAMBDA_ROLE>"
HANDLER="lambda_handler.lambda_handler"
RUNTIME="python3.12"
REGION="us-east-1"

# Package Lambda
zip -r $ZIP_FILE lambda_handler.py

# Check if function exists
aws lambda get-function --function-name $FUNCTION_NAME --region $REGION > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "Updating existing Lambda function..."
    aws lambda update-function-code \
        --function-name $FUNCTION_NAME \
        --zip-file fileb://$ZIP_FILE \
        --region $REGION
else
    echo "Creating new Lambda function..."
    aws lambda create-function \
        --function-name $FUNCTION_NAME \
        --runtime $RUNTIME \
        --role $ROLE_ARN \
        --handler $HANDLER \
        --zip-file fileb://$ZIP_FILE \
        --region $REGION
fi

echo "Deployment done."
