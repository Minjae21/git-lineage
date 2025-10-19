"""
unified_query.py
----------------
Retrieval-Augmented Generation for repository queries.
Uses existing embeddings + FAISS indices to fetch relevant code/commits/PRs,
then feeds them to an LLM (Claude via AWS Bedrock) to answer questions.
"""

import os
import json
import numpy as np
from retrieval.faiss_indexer import query_index
from utils import create_embedding
from config import DATA_DIR, EMBEDDINGS_DIR
import boto3

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

TOP_K = 5

def load_json(path):
    """Load JSON safely."""
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def retrieve_context(query_text):
    """Retrieve top-k items from all FAISS indices."""
    context_sections = []

    # Functions
    functions_results, _ = query_index("functions", query_text, top_k=TOP_K)
    if functions_results:
        context_sections.append("Functions:\n" + "\n".join(
            [f"{i+1}. {item.get('name', 'unknown')}: {item.get('code', '')}" for i, item in enumerate(functions_results)]
        ))

    # Commits
    commits_results, _ = query_index("commits", query_text, top_k=TOP_K)
    if commits_results:
        context_sections.append("Commits:\n" + "\n".join(
            [f"{i+1}. {item.get('message', '')}" for i, item in enumerate(commits_results)]
        ))

    # PRs
    prs_results, _ = query_index("prs", query_text, top_k=TOP_K)
    if prs_results:
        context_sections.append("PRs:\n" + "\n".join(
            [f"{i+1}. {item.get('title', '')}" for i, item in enumerate(prs_results)]
        ))

    return "\n\n".join(context_sections)

def ask_claude(query_text, context_text):
    """Send prompt to Claude via AWS Bedrock."""
    prompt = f"""You are a helpful software assistant. Use the following repository context to answer the user's question.

Context:
{context_text}

Question:
{query_text}

Answer:"""

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    try:
        response = bedrock.invoke_model(
            modelId="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body)
        )

        # Parse response
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text'].strip()

    except Exception as e:
        print(f"Error calling Claude: {e}")
        return "Error generating response."

def query(query_text):
    """Main unified query function."""
    context_text = retrieve_context(query_text)
    if not context_text:
        context_text = "No relevant repository context found."

    answer = ask_claude(query_text, context_text)
    return answer


if __name__ == "__main__":
    query_text = input("Enter your query: ").strip()
    answer = query(query_text)
    print("\n📝 Answer:\n")
    print(answer)
