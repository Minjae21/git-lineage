from opensearchpy import OpenSearch
from config import OPENSEARCH_HOST, OPENSEARCH_USER, OPENSEARCH_PASS

client = OpenSearch(
    hosts=[OPENSEARCH_HOST],
    http_auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
    use_ssl=True,
    verify_certs=True,
    ssl_show_warn=False
)

# settings for k-NN indices
index_settings = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 2,
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100
        }
    },
    "mappings": {
        "properties": {
            "embedding": {
                "type": "knn_vector",
                "dimension": 1024,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil"
                }
            }
        }
    }
}

# fields for commits
commit_mappings = {
    "commit_hash": {"type": "keyword"},
    "repo_name": {"type": "keyword"},
    "author": {"type": "keyword"},
    "author_email": {"type": "keyword"},
    "message": {"type": "text"},
    "timestamp": {"type": "date"},
    "changed_files": {"type": "text"},
}

# fields for PRs
pr_mappings = {
    "pr_number": {"type": "integer"},
    "owner": {"type": "keyword"},
    "repo": {"type": "keyword"},
    "title": {"type": "text"},
    "body": {"type": "text"},
    "merged_at": {"type": "date"},
    "files": {"type": "nested"},
    "commits": {"type": "nested"},
    "review_comments": {"type": "nested"},
}

commit_index_body = index_settings.copy()
commit_index_body["mappings"]["properties"].update(commit_mappings)

pr_index_body = index_settings.copy()
pr_index_body["mappings"]["properties"].update(pr_mappings)

# create index (delete if exists)
def create_index(name, body):
    if client.indices.exists(index=name):
        client.indices.delete(index=name)
        print(f"Deleted existing index '{name}'")
    client.indices.create(index=name, body=body)
    print(f"✅ Index '{name}' created successfully!")

create_index("git-commits", commit_index_body)
create_index("git-prs", pr_index_body)

print("Index info for commits:", client.indices.get(index="git-commits"))
print("Index info for PRs:", client.indices.get(index="git-prs"))
