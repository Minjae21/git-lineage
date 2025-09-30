from xml.dom import NotFoundErr
import requests
import subprocess
import tempfile
import os
from dotenv import load_dotenv
from datetime import datetime
import json
import boto3
from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError
from config import (
     OPENSEARCH_HOST,
     OPENSEARCH_USER,
     OPENSEARCH_PASS,
     EMBEDDING_MODEL_ID,
     AWS_REGION,
)
from utils import create_embedding

load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise ValueError("Github token not found. Please check your .env file.")

class BaseProcessor:
    def __init__(self):
        self.bedrock = boto3.client('bedrock-runtime', region_name=AWS_REGION)
        self.opensearch = OpenSearch(
            hosts=[OPENSEARCH_HOST],
            http_auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
            use_ssl=True,
            verify_certs=True,
            ssl_show_warn=False
        )

class CommitHistoryProcessor(BaseProcessor):
    def __init__(self):
        super().__init__()

    def clone_repo(self, repo_url, target_dir):
        print(f"Cloning {repo_url} now...")
        subprocess.run(['git', 'clone', repo_url, target_dir], check=True)
        print("✅ Repository cloned successfully!")

    def fetch_commits(self, repo_path):
        print("Extracting commits...")

        result = subprocess.run(
            ['git', 'log', '--all', '--pretty=format:%H|%an|%ae|%at|%s', '--reverse'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )

        commits = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split('|', 4)
                if len(parts) == 5:
                    hash, author, email, timestamp, message = parts
                    commits.append({
                        'commit_hash': hash,
                        'author': author,
                        'author_email': email,
                        'timestamp': int(timestamp),
                        'message': message
                    })

        print(f"✅ Found {len(commits)} commits from the repository!")
        return commits

    def changed_files(self, repo_path, commit_hash):
        """ fetching files that were changed in commits """
        result = subprocess.run(
            ['git', 'show', '--pretty=', '--name-only', commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True
        )

        files = [f for f in result.stdout.strip().split('\n') if f]
        return ', '.join(files) if files else 'No files'

    def store_commit(self, commit, repo_name):
        """ storing commit in OpenSearch """

        try:
            self.opensearch.get(index='git-commits', id=commit['commit_hash'])
            print(f"⚠️ Commit {commit['commit_hash'][:7]} already exists in OpenSearch! Skipping.")
            return
        except NotFoundError:
            pass

        doc = {
            'commit_hash': commit['commit_hash'],
            'repo_name': repo_name,
            'author': commit['author'],
            'author_email': commit['author_email'],
            'message': commit['message'],
            'timestamp': datetime.fromtimestamp(commit['timestamp']).isoformat(),
            'changed_files': commit['changed_files'],
            'embedding': commit['embedding']
        }

        self.opensearch.index(
            index='git-commits',
            id=commit['commit_hash'],
            body=doc
        )

    def process_repository(self, repo_url, repo_name):
        """ main processing pipeline """

        print(f"\n{'='*60}")
        print(f"Processing: {repo_name}")
        print(f"URL: {repo_url}")
        print(f"{'='*60}\n")

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_path = os.path.join(tmp_dir, 'repo')

            # phase 1) clone repository
            self.clone_repo(repo_url, repo_path)

            # phase 2) extract commits
            commits = self.fetch_commits(repo_path)

            # phase 3) process each commit
            for i, commit in enumerate(commits, 1):
                print(f"\n[{i}/{len(commits)}] Processing commit {commit['commit_hash'][:7]}...")

                files = self.changed_files(repo_path, commit['commit_hash'])
                commit['changed_files'] = files
                print(f"  Files: {files}")

                print(f"  Creating embedding...")
                richer_input_embedding = f"Message: {commit['message']}\nFiles: {commit['changed_files']}"
                embedding = create_embedding(richer_input_embedding)
                commit['embedding'] = embedding

                print(f"  Storing in OpenSearch...")
                self.store_commit(commit, repo_name)

                print(f"✅ Complete")

            print(f"\n{'='*60}")
            print(f"✅ Nice! Successfully processed {len(commits)} commits!")
            print(f"{'='*60}\n")

class PRHistoryProcessor(BaseProcessor):
    def __init__(self):
        super().__init__()

    def github_headers(self):
        return {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }

    def fetch_merged_prs(self, owner, repo, state="closed"):
        """ fetching merged PRs """
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state={state}"
        response = requests.get(url, headers=self.github_headers())
        if response.status_code != 200:
            raise RuntimeError(f"PR fetch failed: {response.status_code}, {response.text}")
        prs = response.json()
        merged = [pr for pr in prs if pr.get("merged_at")]

        return merged

    def fetch_pr_details(self, owner, repo, pr_number):
        """ fetching core PR details: title, body, etc. """
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        response = requests.get(url, headers=self.github_headers())
        if response.status_code != 200:
            raise RuntimeError(f"PR fetch failed: {response.status_code}")
        return response.json()

    def fetch_pr_commits(self, owner, repo, pr_number):
        """ fetching commits in that PR """
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/commits"
        response = requests.get(url, headers=self.github_headers())
        if response.status_code != 200:
            return []
        return response.json()

    def fetch_pr_files(self, owner, repo, pr_number):
        """ fetching changed files in that PR: additions/deletions """
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        response = requests.get(url, headers=self.github_headers())
        if response.status_code != 200:
            return []
        return response.json()

    def fetch_pr_review_comments(self, owner, repo, pr_number):
        """ fetching inline reivew comments in that PR """
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        response = requests.get(url, headers=self.github_headers())
        if response.status_code != 200:
            return []
        return response.json()

    def process_pr(self, owner, repo, pr_number):
        """ receive a PR object, fetch/extract rich context """
        """ create an embedding -> index into OpenSearch. """

        print(f"Processing PR #{pr_number} from {owner}/{repo}")

        pr = self.fetch_pr_details(owner, repo, pr_number)
        commits = self.fetch_pr_commits(owner, repo, pr_number)
        files = self.fetch_pr_files(owner, repo, pr_number)
        comments = self.fetch_pr_review_comments(owner, repo, pr_number)

        parts = []
        parts.append(f"Title: {pr.get('title','')}")
        parts.append(f"Description: {pr.get('body','')}")
        parts.append(f"Author: {pr.get('user', {}).get('login','')}")
        parts.append(f"Merged at: {pr.get('merged_at','')}")
        parts.append("Files changed:")

        for f in files:
            # e.g. filename, additions, deletions, changes
            parts.append(f"  {f.get('filename')} (+{f.get('additions')} / -{f.get('deletions')})")

        parts.append("Commits in this PR:")
        for c in commits:
            parts.append(f"  {c.get('sha')}: {c.get('commit', {}).get('message')}")

        parts.append("Review comments:")
        for rc in comments:
            parts.append(f"  In file {rc.get('path')} line {rc.get('line', '?')}: {rc.get('body')}")

        pr_text = "\n".join(parts)
        embedding = create_embedding(pr_text)
        doc = {
            "pr_number": pr_number,
            "owner": owner,
            "repo": repo,
            "title": pr.get("title"),
            "body": pr.get("body"),
            "merged_at": pr.get("merged_at"),
            "files": files,
            "commits": commits,
            "review_comments": comments,
            "embedding": embedding
        }

        # index into OpenSearch
        idx_id = f"{owner}_{repo}_{pr_number}"
        self.opensearch.index(index="git-prs", id=idx_id, body=doc)
        print(f"Sucessfully stored PR #{pr_number} in OpenSearch!")

if __name__ == "__main__":
    owner = "#"
    repo = "#"
    repo_url = f"https://github.com/{owner}/{repo}"

    # init processors
    commit_processor = CommitHistoryProcessor()
    pr_processor = PRHistoryProcessor()

    # 1️⃣ process all merged PRs
    merged_prs = pr_processor.fetch_merged_prs(owner, repo)
    for pr in merged_prs:
        print(f"[#{pr['number']}] {pr['title']} (by {pr['user']['login']})")
        pr_processor.process_pr(owner, repo, pr['number'])

    # 2️⃣ process all commits
    commit_processor.process_repository(repo_url, repo)
