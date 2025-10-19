import os
import sys
import json
import numpy as np
from tqdm import tqdm

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils import create_embedding
from config import DATA_DIR, EMBEDDINGS_DIR

"""
This script generates vector embeddings for:
 - Parsed code entities (functions/classes)
 - Commits and PRs (metadata + diffs)

Outputs:
 - functions_embeddings.npy
 - commits_embeddings.npy
 - prs_embeddings.npy
 - Each paired with its JSON source for alignment.
"""

def load_json(path):
    if not os.path.exists(path):
        print(f"Missing file: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_embeddings(data, text_key, output_path):
    """Generate embeddings for each item’s text field."""
    if not data:
        print(f"⚠️ No data found for {output_path}")
        return np.array([])

    print(f"Generating embeddings for {len(data)} items → {output_path}")

    embeddings = []
    valid_count = 0
    for item in tqdm(data, desc=f"Embedding {os.path.basename(output_path)}"):
        text = item.get(text_key)
        if text and text.strip():
            try:
                emb = create_embedding(text)
                embeddings.append(emb)
                valid_count += 1
            except Exception as e:
                print(f"⚠️ Failed to embed item ({text_key}): {e}")
                embeddings.append(np.zeros(1536))
        else:
            # Skip PRs without title
            continue

    if not embeddings:
        print(f"⚠️ No valid embeddings generated for {output_path}")
        return np.array([])

    embeddings = np.array(embeddings)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    np.save(output_path, embeddings)
    print(f"✅ Saved {valid_count} embeddings → {output_path}")
    return embeddings

def main():
    os.makedirs(EMBEDDINGS_DIR, exist_ok=True)

    # loading parsed data
    functions_data = load_json(os.path.join(DATA_DIR, "functions_test.json"))
    commits_data = load_json(os.path.join(DATA_DIR, "commits.json"))
    prs_data = load_json(os.path.join(DATA_DIR, "prs.json"))

    # generating embeddings
    generate_embeddings(functions_data, "code", os.path.join(EMBEDDINGS_DIR, "functions_embeddings.npy"))
    generate_embeddings(commits_data, "message", os.path.join(EMBEDDINGS_DIR, "commits_embeddings.npy"))
    generate_embeddings(prs_data, "title", os.path.join(EMBEDDINGS_DIR, "prs_embeddings.npy"))

    print("\n🎉 All embeddings generated successfully!")

if __name__ == "__main__":
    main()
