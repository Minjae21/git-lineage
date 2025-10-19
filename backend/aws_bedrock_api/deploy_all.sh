#!/bin/bash

# Variables - UPDATE THESE WITH YOUR VALUES
FUNCTION_NAME_PREFIX="git-lineage"
ZIP_FILE="lambda_function.zip"
ROLE_ARN="arn:aws:iam::<ACCOUNT_ID>:role/<BEDROCK_LAMBDA_ROLE>"
RUNTIME="python3.12"
REGION="us-east-1"
S3_BUCKET="<YOUR_S3_BUCKET_NAME>"
API_GATEWAY_NAME="git-lineage-api"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Deploying Git Lineage API to AWS${NC}"

# Function to deploy a Lambda function
deploy_lambda() {
    local function_name=$1
    local handler_file=$2
    local description=$3

    echo -e "${YELLOW}📦 Deploying $function_name...${NC}"

    # Create deployment package
    cd lambda_function
    zip -r ../$ZIP_FILE . -x "*.pyc" "__pycache__/*" "*.git*"
    cd ..

    # Check if function exists
    aws lambda get-function --function-name $function_name --region $REGION > /dev/null 2>&1

    if [ $? -eq 0 ]; then
        echo "Updating existing Lambda function: $function_name"
        aws lambda update-function-code \
            --function-name $function_name \
            --zip-file fileb://$ZIP_FILE \
            --region $REGION
    else
        echo "Creating new Lambda function: $function_name"
        aws lambda create-function \
            --function-name $function_name \
            --runtime $RUNTIME \
            --role $ROLE_ARN \
            --handler $handler_file \
            --zip-file fileb://$ZIP_FILE \
            --description "$description" \
            --timeout 900 \
            --memory-size 1024 \
            --environment Variables="{S3_BUCKET_NAME=$S3_BUCKET}" \
            --region $REGION
    fi

    # Clean up
    rm -f $ZIP_FILE

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ $function_name deployed successfully${NC}"
    else
        echo -e "${RED}❌ Failed to deploy $function_name${NC}"
        exit 1
    fi
}

# Deploy all Lambda functions
deploy_lambda "${FUNCTION_NAME_PREFIX}-process" "process_handler.lambda_handler" "Process GitHub repositories"
deploy_lambda "${FUNCTION_NAME_PREFIX}-stats" "stats_handler.lambda_handler" "Get repository statistics"
deploy_lambda "${FUNCTION_NAME_PREFIX}-query" "query_handler.lambda_handler" "Handle repository queries"
deploy_lambda "${FUNCTION_NAME_PREFIX}-bedrock" "lambda_handler.lambda_handler" "AWS Bedrock integration"

echo -e "${YELLOW}🌐 Setting up API Gateway...${NC}"

# Create API Gateway
API_ID=$(aws apigateway create-rest-api \
    --name $API_GATEWAY_NAME \
    --description "Git Lineage Analysis API" \
    --region $REGION \
    --query 'id' \
    --output text 2>/dev/null)

if [ -z "$API_ID" ]; then
    # API already exists, get its ID
    API_ID=$(aws apigateway get-rest-apis \
        --region $REGION \
        --query "items[?name=='$API_GATEWAY_NAME'].id" \
        --output text)
fi

echo "API Gateway ID: $API_ID"

# Get root resource ID
ROOT_RESOURCE_ID=$(aws apigateway get-resources \
    --rest-api-id $API_ID \
    --region $REGION \
    --query 'items[?path==`/`].id' \
    --output text)

# Create resources and methods
create_api_endpoint() {
    local path=$1
    local method=$2
    local function_name=$3
    local resource_name=$4

    echo "Creating endpoint: $method $path"

    # Create resource if it doesn't exist
    RESOURCE_ID=$(aws apigateway get-resources \
        --rest-api-id $API_ID \
        --region $REGION \
        --query "items[?path=='$path'].id" \
        --output text)

    if [ -z "$RESOURCE_ID" ]; then
        RESOURCE_ID=$(aws apigateway create-resource \
            --rest-api-id $API_ID \
            --parent-id $ROOT_RESOURCE_ID \
            --path-part $resource_name \
            --region $REGION \
            --query 'id' \
            --output text)
    fi

    # Get Lambda function ARN
    LAMBDA_ARN=$(aws lambda get-function \
        --function-name $function_name \
        --region $REGION \
        --query 'Configuration.FunctionArn' \
        --output text)

    # Create method
    aws apigateway put-method \
        --rest-api-id $API_ID \
        --resource-id $RESOURCE_ID \
        --http-method $method \
        --authorization-type NONE \
        --region $REGION

    # Set up Lambda integration
    aws apigateway put-integration \
        --rest-api-id $API_ID \
        --resource-id $RESOURCE_ID \
        --http-method $method \
        --type AWS_PROXY \
        --integration-http-method POST \
        --uri "arn:aws:apigateway:$REGION:lambda:path/2015-03-31/functions/$LAMBDA_ARN/invocations" \
        --region $REGION

    # Add permission for API Gateway to invoke Lambda
    aws lambda add-permission \
        --function-name $function_name \
        --statement-id "api-gateway-invoke-$(date +%s)" \
        --action lambda:InvokeFunction \
        --principal apigateway.amazonaws.com \
        --source-arn "arn:aws:execute-api:$REGION:*:$API_ID/*/*" \
        --region $REGION > /dev/null 2>&1
}

# Create API endpoints
create_api_endpoint "/process" "POST" "${FUNCTION_NAME_PREFIX}-process" "process"
create_api_endpoint "/stats" "POST" "${FUNCTION_NAME_PREFIX}-stats" "stats"
create_api_endpoint "/query" "POST" "${FUNCTION_NAME_PREFIX}-query" "query"
create_api_endpoint "/bedrock" "POST" "${FUNCTION_NAME_PREFIX}-bedrock" "bedrock"

# Deploy API
echo -e "${YELLOW}🚀 Deploying API Gateway...${NC}"
aws apigateway create-deployment \
    --rest-api-id $API_ID \
    --stage-name prod \
    --region $REGION

# Get API Gateway URL
API_URL="https://$API_ID.execute-api.$REGION.amazonaws.com/prod"
echo -e "${GREEN}🎉 Deployment complete!${NC}"
echo -e "${GREEN}API Gateway URL: $API_URL${NC}"
echo ""
echo -e "${YELLOW}📝 Next steps:${NC}"
echo "1. Update the API_BASE_URL in frontend/index.html with: $API_URL"
echo "2. Make sure your S3 bucket '$S3_BUCKET' exists and is accessible"
echo "3. Ensure your Lambda execution role has permissions for:"
echo "   - AWS Bedrock (bedrock:InvokeModel)"
echo "   - S3 (s3:GetObject, s3:PutObject)"
echo "   - API Gateway (execute-api:Invoke)"
echo ""
echo -e "${GREEN}🔗 Available endpoints:${NC}"
echo "  POST $API_URL/process  - Process a GitHub repository"
echo "  POST $API_URL/stats    - Get repository statistics"
echo "  POST $API_URL/query    - Query repository with AI"
echo "  POST $API_URL/bedrock  - Direct Bedrock integration"


