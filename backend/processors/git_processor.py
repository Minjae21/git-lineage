import os
import json
import tempfile
import subprocess
import requests
from typing import List, Dict, Optional
from config import GITHUB_TOKEN, MAX_COMMITS, MAX_PRS, MAX_COMMITS_PER_PAGE, MAX_PRS_PER_PAGE, DATA_DIR

class GitProcessor:
    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or GITHUB_TOKEN
        self.session = requests.Session()
        if self.github_token:
            self.session.headers.update({
                'Authorization': f'token {self.github_token}',
                'Accept': 'application/vnd.github.v3+json'
            })

    def extract_repo_info(self, repo_url: str) -> Dict[str, str]:
        """Extract owner and repo name from GitHub URL."""
        # handle different URL formats
        if repo_url.startswith('https://github.com/'):
            parts = repo_url.replace('https://github.com/', '').rstrip('/').split('/')
        elif repo_url.startswith('git@github.com:'):
            parts = repo_url.replace('git@github.com:', '').replace('.git', '').split('/')
        else:
            raise ValueError(f"Unsupported repository URL format: {repo_url}")

        if len(parts) != 2:
            raise ValueError(f"Invalid repository URL format: {repo_url}")

        return {
            'owner': parts[0],
            'repo': parts[1],
            'api_url': f"https://api.github.com/repos/{parts[0]}/{parts[1]}"
        }

    def fetch_commits(self, repo_info: Dict[str, str]) -> List[Dict]:
        """Fetch commit history from GitHub API."""
        commits = []
        page = 1

        print(f"Fetching commits for {repo_info['owner']}/{repo_info['repo']}...")

        while len(commits) < MAX_COMMITS:
            url = f"{repo_info['api_url']}/commits"
            params = {
                'per_page': min(MAX_COMMITS_PER_PAGE, MAX_COMMITS - len(commits)),
                'page': page
            }

            try:
                response = self.session.get(url, params=params)
                response.raise_for_status()
                page_commits = response.json()

                if not page_commits:
                    break

                for commit in page_commits:
                    commit_data = {
                        'sha': commit['sha'],
                        'message': commit['commit']['message'],
                        'author': {
                            'name': commit['commit']['author']['name'],
                            'email': commit['commit']['author']['email'],
                            'date': commit['commit']['author']['date']
                        },
                        'committer': {
                            'name': commit['commit']['committer']['name'],
                            'email': commit['commit']['committer']['email'],
                            'date': commit['commit']['committer']['date']
                        },
                        'url': commit['html_url'],
                        'code_diff': ''
                    }

                    # fetch detailed commit info with diff
                    try:
                        detail_response = self.session.get(commit['url'])
                        detail_response.raise_for_status()
                        detail_data = detail_response.json()

                        # extract code diff from files
                        if 'files' in detail_data:
                            diff_parts = []
                            for file in detail_data['files']:
                                if file.get('patch'):
                                    diff_parts.append(f"--- {file['filename']}\n{file['patch']}")
                            commit_data['code_diff'] = '\n'.join(diff_parts)
                    except Exception as e:
                        print(f"Warning: Could not fetch diff for commit {commit['sha']}: {e}")

                    commits.append(commit_data)

                page += 1

                if len(page_commits) < MAX_COMMITS_PER_PAGE:
                    break

            except requests.exceptions.RequestException as e:
                print(f"Error fetching commits: {e}")
                break

        print(f"✅ Fetched {len(commits)} commits")
        return commits

    def fetch_pull_requests(self, repo_info: Dict[str, str]) -> List[Dict]:
        """Fetch pull request history from GitHub API."""
        prs = []
        page = 1

        print(f"Fetching pull requests for {repo_info['owner']}/{repo_info['repo']}...")

        while len(prs) < MAX_PRS:
            url = f"{repo_info['api_url']}/pulls"
            params = {
                'state': 'all',
                'per_page': min(MAX_PRS_PER_PAGE, MAX_PRS - len(prs)),
                'page': page,
                'sort': 'updated',
                'direction': 'desc'
            }

            try:
                response = self.session.get(url, params=params)
                response.raise_for_status()
                page_prs = response.json()

                if not page_prs:
                    break

                for pr in page_prs:
                    pr_data = {
                        'number': pr['number'],
                        'title': pr['title'],
                        'body': pr['body'] or '',
                        'state': pr['state'],
                        'created_at': pr['created_at'],
                        'updated_at': pr['updated_at'],
                        'closed_at': pr['closed_at'],
                        'merged_at': pr['merged_at'],
                        'user': {
                            'login': pr['user']['login'],
                            'avatar_url': pr['user']['avatar_url']
                        },
                        'head': {
                            'ref': pr['head']['ref'],
                            'sha': pr['head']['sha']
                        },
                        'base': {
                            'ref': pr['base']['ref'],
                            'sha': pr['base']['sha']
                        },
                        'url': pr['html_url'],
                        'diff_url': pr['diff_url'],
                        'patch_url': pr['patch_url']
                    }

                    # fetch PR diff if available
                    try:
                        if pr_data['patch_url']:
                            diff_response = self.session.get(pr_data['patch_url'])
                            if diff_response.status_code == 200:
                                pr_data['code_diff'] = diff_response.text
                            else:
                                pr_data['code_diff'] = ''
                        else:
                            pr_data['code_diff'] = ''
                    except Exception as e:
                        print(f"Warning: Could not fetch diff for PR #{pr['number']}: {e}")
                        pr_data['code_diff'] = ''

                    prs.append(pr_data)

                page += 1

                if len(page_prs) < MAX_PRS_PER_PAGE:
                    break

            except requests.exceptions.RequestException as e:
                print(f"Error fetching pull requests: {e}")
                break

        print(f"✅ Fetched {len(prs)} pull requests")
        return prs

    def clone_repository(self, repo_url: str) -> str:
        """Clone repository to temporary directory and return path."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_path = os.path.join(tmp_dir, "repo")
            print(f"Cloning {repo_url}...")

            try:
                subprocess.run([
                    'git', 'clone', '--depth', '1', '--single-branch',
                    repo_url, repo_path
                ], check=True, capture_output=True, text=True)

                print(f"✅ Repository cloned successfully")
                return repo_path

            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to clone repository: {e}")
                print(f"Error output: {e.stderr}")
                raise

    def process_repository(self, repo_url: str, output_dir: str = DATA_DIR) -> Dict[str, str]:
        """
        Process a GitHub repository: fetch commits, PRs, and save to files.
        Returns paths to saved files.
        """
        try:
            # extract repository information
            repo_info = self.extract_repo_info(repo_url)
            print(f"Processing repository: {repo_info['owner']}/{repo_info['repo']}")

            os.makedirs(output_dir, exist_ok=True)

            commits = self.fetch_commits(repo_info)
            prs = self.fetch_pull_requests(repo_info)

            commits_path = os.path.join(output_dir, "commits.json")
            prs_path = os.path.join(output_dir, "prs.json")

            with open(commits_path, 'w', encoding='utf-8') as f:
                json.dump(commits, f, indent=2, ensure_ascii=False)

            with open(prs_path, 'w', encoding='utf-8') as f:
                json.dump(prs, f, indent=2, ensure_ascii=False)

            print(f"✅ Saved {len(commits)} commits to {commits_path}")
            print(f"✅ Saved {len(prs)} pull requests to {prs_path}")

            return {
                'commits_path': commits_path,
                'prs_path': prs_path,
                'commits_count': len(commits),
                'prs_count': len(prs)
            }

        except Exception as e:
            print(f"❌ Error processing repository: {e}")
            raise

def main():
    """Command line interface for git processor."""
    import argparse

    parser = argparse.ArgumentParser(description="Process GitHub repository metadata")
    parser.add_argument("--url", required=True, help="GitHub repository URL")
    parser.add_argument("--token", help="GitHub personal access token")
    parser.add_argument("--output", default=DATA_DIR, help="Output directory")

    args = parser.parse_args()

    processor = GitProcessor(github_token=args.token)
    result = processor.process_repository(args.url, args.output)

    print(f"\n📊 Summary:")
    print(f"  Commits: {result['commits_count']}")
    print(f"  Pull Requests: {result['prs_count']}")
    print(f"  Output files: {result['commits_path']}, {result['prs_path']}")

if __name__ == "__main__":
    main()