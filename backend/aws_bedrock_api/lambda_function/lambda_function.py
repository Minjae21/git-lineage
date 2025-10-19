import json
import os
import boto3
import traceback
import urllib.request
import urllib.error

# -----------------------------
# AWS Clients
# -----------------------------
REGION = "us-east-1"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")
LLM_MODEL = os.getenv("LLM_MODEL_ID", "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

# Constants
MAX_COMMITS = 50
MAX_PRS = 30

# -----------------------------
# Helper Functions
# -----------------------------

def create_embedding(text):
    """Create embedding using Bedrock Titan."""
    try:
        payload = {"inputText": text[:8000]}  # Limit text length
        response = bedrock.invoke_model(
            modelId=EMBEDDING_MODEL,
            contentType="application/json",
            body=json.dumps(payload)
        )
        result = json.loads(response['body'].read())
        return result.get("embedding", [])
    except Exception as e:
        print(f"Embedding error: {e}")
        return []

def extract_repo_info(repo_url):
    """Extract owner and repo name from GitHub URL."""
    if repo_url.startswith('https://github.com/'):
        parts = repo_url.replace('https://github.com/', '').rstrip('/').split('/')
    else:
        raise ValueError(f"Unsupported repository URL format: {repo_url}")

    if len(parts) < 2:
        raise ValueError(f"Invalid repository URL format: {repo_url}")

    return {
        'owner': parts[0],
        'repo': parts[1],
        'full_name': f"{parts[0]}/{parts[1]}",
        'api_url': f"https://api.github.com/repos/{parts[0]}/{parts[1]}"
    }

def github_api_request(url, github_token=None):
    """Make GitHub API request using urllib."""
    try:
        req = urllib.request.Request(url)
        req.add_header('Accept', 'application/vnd.github.v3+json')
        req.add_header('User-Agent', 'Git-Lineage-Lambda')

        if github_token:
            req.add_header('Authorization', f'token {github_token}')

        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        print(f"GitHub API error: {e.code} - {e.reason}")
        return None
    except Exception as e:
        print(f"Request error: {e}")
        return None

def fetch_commits(repo_info, github_token):
    """Fetch commits from GitHub API."""
    commits = []
    url = f"{repo_info['api_url']}/commits?per_page={MAX_COMMITS}&page=1"

    print(f"Fetching commits from {url}")
    data = github_api_request(url, github_token)

    if not data:
        return []

    for commit in data[:MAX_COMMITS]:
        try:
            commits.append({
                'sha': commit['sha'],
                'message': commit['commit']['message'],
                'author': commit['commit']['author']['name'],
                'date': commit['commit']['author']['date'],
                'url': commit['html_url']
            })
        except KeyError as e:
            print(f"Error parsing commit: {e}")
            continue

    print(f"Fetched {len(commits)} commits")
    return commits

def fetch_pull_requests(repo_info, github_token):
    """Fetch PRs from GitHub API."""
    prs = []
    url = f"{repo_info['api_url']}/pulls?state=all&per_page={MAX_PRS}&page=1"

    print(f"Fetching PRs from {url}")
    data = github_api_request(url, github_token)

    if not data:
        return []

    for pr in data[:MAX_PRS]:
        try:
            prs.append({
                'number': pr['number'],
                'title': pr['title'],
                'state': pr['state'],
                'user': pr['user']['login'],
                'created_at': pr['created_at'],
                'url': pr['html_url']
            })
        except KeyError as e:
            print(f"Error parsing PR: {e}")
            continue

    print(f"Fetched {len(prs)} PRs")
    return prs

def fetch_repo_info(repo_info, github_token):
    """Fetch basic repository information."""
    url = repo_info['api_url']

    print(f"Fetching repo info from {url}")
    data = github_api_request(url, github_token)

    if not data:
        return {}

    try:
        return {
            'name': data.get('name', ''),
            'description': data.get('description', ''),
            'language': data.get('language', ''),
            'stars': data.get('stargazers_count', 0),
            'forks': data.get('forks_count', 0),
            'open_issues': data.get('open_issues_count', 0)
        }
    except Exception as e:
        print(f"Error parsing repo info: {e}")
        return {}

def process_repository(repo_url, github_token):
    """Process repository: fetch metadata from GitHub API."""
    print(f"Processing repository: {repo_url}")

    try:
        repo_info = extract_repo_info(repo_url)
        print(f"Repository: {repo_info['full_name']}")

        # Fetch data from GitHub API
        repo_details = fetch_repo_info(repo_info, github_token)
        commits = fetch_commits(repo_info, github_token)
        prs = fetch_pull_requests(repo_info, github_token)

        result = {
            'repo': repo_info['full_name'],
            'details': repo_details,
            'commits': commits,
            'prs': prs,
            'stats': {
                'commits_count': len(commits),
                'prs_count': len(prs),
                'functions_count': 0  # Would need code parsing
            }
        }

        print(f"Processing complete: {len(commits)} commits, {len(prs)} PRs")
        return result

    except Exception as e:
        print(f"Error processing repository: {e}")
        print(traceback.format_exc())
        raise

def build_context(repo_data):
    """Build context string from repository data."""
    context_parts = []

    # Repository info
    if repo_data.get('details'):
        details = repo_data['details']
        context_parts.append(f"Repository: {repo_data.get('repo', 'unknown')}")
        if details.get('description'):
            context_parts.append(f"Description: {details['description']}")
        if details.get('language'):
            context_parts.append(f"Primary Language: {details['language']}")
        context_parts.append(f"Stars: {details.get('stars', 0)}, Forks: {details.get('forks', 0)}")

    # Recent commits
    if repo_data.get('commits'):
        commits_text = "\n".join([
            f"- {c['message'][:100]} (by {c['author']})"
            for c in repo_data['commits'][:10]
        ])
        context_parts.append(f"\nRecent Commits:\n{commits_text}")

    # Recent PRs
    if repo_data.get('prs'):
        prs_text = "\n".join([
            f"- PR #{p['number']}: {p['title'][:100]} ({p['state']})"
            for p in repo_data['prs'][:10]
        ])
        context_parts.append(f"\nRecent Pull Requests:\n{prs_text}")

    return "\n\n".join(context_parts)

# -----------------------------
# Lambda Handler
# -----------------------------

# In-memory storage (temporary - use DynamoDB in production)
REPO_CACHE = {}

def lambda_handler(event, context):
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
        "Access-Control-Allow-Methods": "POST,OPTIONS"
    }

    # Handle OPTIONS
    if event.get('httpMethod') == 'OPTIONS':
        return {"statusCode": 200, "headers": headers, "body": ""}

    try:
        print(f"Received event: {json.dumps(event)}")

        if isinstance(event.get("body"), str):
            body = json.loads(event.get("body", "{}"))
        else:
            body = event

        action = body.get("action")
        print(f"Action: {action}")

        if action == "process":
            # Process repository
            repo_url = body.get("repo_url")
            if not repo_url:
                return {
                    "statusCode": 400,
                    "headers": headers,
                    "body": json.dumps({"error": "repo_url required"})
                }

            print(f"Processing repo: {repo_url}")
            result = process_repository(repo_url, GITHUB_TOKEN)

            # Cache the result
            REPO_CACHE[repo_url] = result

            return {
                "statusCode": 200,
                "headers": headers,
                "body": json.dumps({
                    "message": "Repository processed successfully",
                    "stats": result['stats']
                })
            }

        elif action == "ask":
            # Answer question with context
            text = body.get("text", "")
            repo_url = body.get("repo_url", "")

            print(f"Question: {text}")
            print(f"Repo URL: {repo_url}")

            # Get cached repo data
            repo_data = REPO_CACHE.get(repo_url, {})

            # Build context
            if repo_data:
                context = build_context(repo_data)
                prompt = f"""You are analyzing the GitHub repository: {repo_data.get('repo', 'unknown')}

Repository Context:
{context}

User Question: {text}

Please provide a helpful answer based on the repository context above."""
            else:
                prompt = f"""The user is asking about a GitHub repository: {repo_url}

Question: {text}

Please provide a helpful answer. Note: Detailed repository analysis may not be available yet."""

            # Call Claude
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}]
            }

            response = bedrock.invoke_model(
                modelId=LLM_MODEL,
                contentType="application/json",
                body=json.dumps(payload)
            )

            result = json.loads(response['body'].read())
            answer = result['content'][0]['text']

            return {
                "statusCode": 200,
                "headers": headers,
                "body": json.dumps({"answer": answer})
            }

        elif action == "embed":
            # Create embedding
            text = body.get("text", "")
            embedding = create_embedding(text)

            return {
                "statusCode": 200,
                "headers": headers,
                "body": json.dumps({"embedding": embedding})
            }

        else:
            return {
                "statusCode": 400,
                "headers": headers,
                "body": json.dumps({"error": "Invalid action. Use 'process', 'ask', or 'embed'"})
            }

    except Exception as e:
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"Error: {error_msg}")
        print(f"Traceback: {error_trace}")

        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({
                "error": error_msg,
                "type": type(e).__name__
            })
        }