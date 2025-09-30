import json
import boto3
from opensearchpy import OpenSearch
from config import (
    OPENSEARCH_HOST,
    OPENSEARCH_USER,
    OPENSEARCH_PASS,
    AWS_REGION,
    EMBEDDING_MODEL_ID,
    CLAUDE_MODEL_ID
)
from utils import create_embedding

bedrock = boto3.client('bedrock-runtime', region_name=AWS_REGION)
opensearch = OpenSearch(
    hosts=[OPENSEARCH_HOST],
    http_auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
    use_ssl=True,
    verify_certs=True,
    ssl_show_warn=False
)

def search_all(query, top_k=5):
    """ using semantic similarity """
    print(f"\n Searching for: '{query}'\n")

    # phase 1) converts the natural language query into embedding
    query_embedding = create_embedding(query)

    body = {
        'size': top_k,
        'query': {
            'knn': {
                'embedding': {
                    'vector': query_embedding,
                    'k': top_k
                }
            }
        }
    }

    # phase 2) run k-NN in opensearch
    try:
        res_commits = opensearch.search(index="git-commits", body=body)
        res_prs = opensearch.search(index="git-prs", body=body)

    except Exception as e:
        print(f"⚠️ OpenSearch query failed: {e}")
        return []

    # phase 3) combine, label results
    hits = []
    for h in res_commits.get("hits", {}).get("hits", []):
        hits.append(("commit", h))
    for h in res_prs.get("hits", {}).get("hits", []):
        hits.append(("pr", h))

    hits.sort(key=lambda x: x[1]["_score"], reverse=True)
    return hits

def ask_claude(query, context_commits, context_prs):
    """Ask Claude using commit and PR history."""

    pr_context = "Relevant PRs:\n\n"
    for pr in context_prs:
        pr_context += f"- PR #{pr.get('pr_number')} Title: {pr.get('title')}\n"
        pr_context += f"  Author: {pr.get('user')}, Merged at: {pr.get('merged_at')}\n"
        pr_context += f"  Files changed: {', '.join([f.get('filename', '') for f in pr.get('files', [])])}\n"
        pr_context += f"  Comments: {len(pr.get('review_comments', []))} review comments\n\n"

    commit_context = "Relevant commits:\n\n"
    for commit in context_commits:
        commit_context += f"- [{commit['commit_hash'][:7]}] {commit['message']}\n"
        commit_context += f"  Author: {commit['author']}, Files: {commit['changed_files']}\n\n"

    prompt = f"""
You are an AI assistant helping analyze a GitHub repository's history.
Here are some relevant results (PRs and commits):

{pr_context}
{commit_context}

Using the commit history above, answer the following question:

Question: {query}
"""

    bedrock = boto3.client('bedrock-runtime', region_name=AWS_REGION)

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}]
    })

    response = bedrock.invoke_model(modelId=CLAUDE_MODEL_ID, body=body)
    raw = response['body'].read()
    result = json.loads(raw.decode('utf-8'))

    # clean extraction
    if "content" in result and len(result["content"]) > 0:
        return result["content"][0].get("text", "")
    elif "completion" in result:
        return result["completion"]
    else:
        return "⚠️ Unable to extract answer from Claude."

if __name__ == "__main__":
    query = input("Enter your question about the repo: ")
    hits = search_all(query, top_k=3)

    if not hits:
        print(f"⚠️ No relevant commits or PRs found. Try another question?")
    else:
        commits = [h[1]['_source'] for h in hits if h[0] == 'commit']
        prs = [h[1]['_source'] for h in hits if h[0] == 'pr']
        print("\n" + "="*60)
        print("Asking Claude about the repository...")
        print("="*60 + "\n")

        answer = ask_claude(query, commits, prs)

        print(f"Claude's Answer: {answer}\n")