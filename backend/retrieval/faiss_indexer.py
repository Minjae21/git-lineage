import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import json
import numpy as np
import faiss
from utils import create_embedding
from config import DATA_DIR, EMBEDDINGS_DIR


def build_faiss_index(name):
    """Create a FAISS index from saved embeddings"""
    npy_path = os.path.join(EMBEDDINGS_DIR, f"{name}_embeddings.npy")
    if not os.path.exists(npy_path):
        raise FileNotFoundError(f"❌ Missing embedding file: {npy_path}")

    vectors = np.load(npy_path)
    dim = vectors.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)
    faiss.write_index(index, os.path.join(EMBEDDINGS_DIR, f"{name}_index.faiss"))
    print(f"✅ Built FAISS index for {name}: {vectors.shape[0]} vectors")
    return index


def load_index(name):
    """Load existing FAISS index"""
    path = os.path.join(EMBEDDINGS_DIR, f"{name}_index.faiss")
    if not os.path.exists(path):
        print(f"⚠️ No FAISS index found for {name}, building new one...")
        return build_faiss_index(name)
    return faiss.read_index(path)


def query_index(name, query_text, top_k=5):
    """Query FAISS index with an embedded query"""
    data_path = os.path.join(DATA_DIR, f"{name}.json")
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Missing data file for {name}: {data_path}")

    data = json.load(open(data_path))
    index = load_index(name)

    query_vec = np.array([create_embedding(query_text)]).astype('float32')
    D, I = index.search(query_vec, top_k)

    results = [data[i] for i in I[0] if i < len(data)]
    return results, D[0]


if __name__ == "__main__":
    # quick test
    name = input("Enter index name (e.g., 'functions_test' or 'commits'): ").strip()
    query_text = input("Enter query text: ").strip()
    results, scores = query_index(name, query_text)
    print("\nTop Results:")
    for i, (res, score) in enumerate(zip(results, scores)):
        print(f"{i+1}. {res.get('name', 'unknown')} (score: {score:.4f})")
