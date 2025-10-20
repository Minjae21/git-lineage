import json
import os
import boto3
import traceback
import urllib.request
import urllib.error
import tempfile
import subprocess
import sqlite3
from datetime import datetime

# -----------------------------
# AWS Clients
# -----------------------------
REGION = "us-east-1"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")
LLM_MODEL = os.getenv("LLM_MODEL_ID", "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)

# Configuration
S3_BUCKET = os.getenv("S3_BUCKET", "git-lineage-data")
MAX_COMMITS = 50
MAX_PRS = 30
SUPPORTED_EXTENSIONS = (".py", ".js", ".ts", ".java", ".go", ".cpp", ".c", ".jsx", ".tsx")

# In-memory cache
REPO_CACHE = {}

# -----------------------------
# Database Functions (SQLite in /tmp)
# -----------------------------

def init_db(db_path):
    """Initialize SQLite database with schema."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS commits (
            commit_sha TEXT PRIMARY KEY,
            author_name TEXT,
            author_email TEXT,
            message TEXT,
            committed_at DATETIME
        );

        CREATE TABLE IF NOT EXISTS files (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            current_path TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS symbols (
            symbol_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            commit_sha TEXT NOT NULL,
            kind TEXT CHECK (kind IN ('function','class')),
            name TEXT NOT NULL,
            start_line INTEGER,
            end_line INTEGER,
            FOREIGN KEY (file_id) REFERENCES files(file_id),
            FOREIGN KEY (commit_sha) REFERENCES commits(commit_sha)
        );

        CREATE INDEX IF NOT EXISTS idx_symbols_file_commit ON symbols (file_id, commit_sha);
        CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols (name);
    """)
    conn.commit()
    return conn

def insert_commit(conn, sha, author_name, author_email, message, date):
    """Insert commit into database."""
    conn.execute(
        "INSERT OR IGNORE INTO commits (commit_sha, author_name, author_email, message, committed_at) VALUES (?, ?, ?, ?, ?)",
        (sha, author_name, author_email, message, date)
    )

def insert_file(conn, path):
    """Insert file and return file_id."""
    conn.execute("INSERT OR IGNORE INTO files (current_path) VALUES (?)", (path,))
    cursor = conn.execute("SELECT file_id FROM files WHERE current_path = ?", (path,))
    return cursor.fetchone()[0]

def insert_symbol(conn, file_id, commit_sha, kind, name, start_line, end_line):
    """Insert symbol into database."""
    conn.execute(
        "INSERT INTO symbols (file_id, commit_sha, kind, name, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?)",
        (file_id, commit_sha, kind, name, start_line, end_line)
    )

def query_symbols_by_name(conn, name_pattern):
    """Search symbols by name."""
    cursor = conn.execute("""
        SELECT f.current_path, s.kind, s.name, s.start_line, s.end_line
        FROM symbols s
        JOIN files f ON s.file_id = f.file_id
        WHERE s.name LIKE ?
        ORDER BY f.current_path
    """, (f"%{name_pattern}%",))
    return cursor.fetchall()

def get_all_symbols(conn):
    """Get all symbols with file paths."""
    cursor = conn.execute("""
        SELECT f.current_path, s.kind, s.name, s.start_line, s.end_line
        FROM symbols s
        JOIN files f ON s.file_id = f.file_id
        ORDER BY f.current_path, s.start_line
    """)
    return cursor.fetchall()

def get_file_statistics(conn):
    """Get statistics about files and symbols."""
    cursor = conn.execute("""
        SELECT
            f.current_path,
            COUNT(CASE WHEN s.kind='function' THEN 1 END) as functions,
            COUNT(CASE WHEN s.kind='class' THEN 1 END) as classes
        FROM files f
        LEFT JOIN symbols s ON f.file_id = s.file_id
        GROUP BY f.current_path
        ORDER BY (functions + classes) DESC
    """)
    return cursor.fetchall()

# -----------------------------
# Simple Python Parser (AST-based, no tree-sitter needed)
# -----------------------------

def parse_python_file(file_path, content):
    """Parse Python file using built-in AST module."""
    import ast

    try:
        tree = ast.parse(content)
        symbols = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                symbols.append(('function', node.name, node.lineno, node.end_lineno or node.lineno))
            elif isinstance(node, ast.ClassDef):
                symbols.append(('class', node.name, node.lineno, node.end_lineno or node.lineno))

        return symbols
    except SyntaxError as e:
        print(f"Syntax error in {file_path}: {e}")
        return []
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return []

def parse_file(file_path, content):
    """Route to appropriate parser based on file extension."""
    if file_path.endswith('.py'):
        return parse_python_file(file_path, content)
    # Add more parsers here (JS, TS, etc.)
    return []

# -----------------------------
# GitHub API Functions
# -----------------------------

def extract_repo_info(repo_url):
    """Extract owner and repo from URL."""
    if repo_url.startswith('https://github.com/'):
        parts = repo_url.replace('https://github.com/', '').rstrip('/').split('/')
    else:
        raise ValueError(f"Invalid GitHub URL: {repo_url}")

    if len(parts) < 2:
        raise ValueError(f"Invalid repository URL format: {repo_url}")

    return {
        'owner': parts[0],
        'repo': parts[1],
        'full_name': f"{parts[0]}/{parts[1]}",
        'api_url': f"https://api.github.com/repos/{parts[0]}/{parts[1]}"
    }

def github_api_request(url, github_token=None):
    """Make GitHub API request."""
    try:
        req = urllib.request.Request(url)
        req.add_header('Accept', 'application/vnd.github.v3+json')
        req.add_header('User-Agent', 'Git-Lineage-Lambda')

        if github_token:
            req.add_header('Authorization', f'token {github_token}')

        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"API request error: {e}")
        return None

def fetch_commits(repo_info, github_token):
    """Fetch recent commits."""
    url = f"{repo_info['api_url']}/commits?per_page={MAX_COMMITS}"
    data = github_api_request(url, github_token)

    if not data:
        return []

    commits = []
    for c in data[:MAX_COMMITS]:
        try:
            commits.append({
                'sha': c['sha'],
                'message': c['commit']['message'],
                'author': c['commit']['author']['name'],
                'email': c['commit']['author']['email'],
                'date': c['commit']['author']['date']
            })
        except:
            continue

    return commits

def fetch_pull_requests(repo_info, github_token):
    """Fetch recent PRs."""
    url = f"{repo_info['api_url']}/pulls?state=all&per_page={MAX_PRS}"
    data = github_api_request(url, github_token)

    if not data:
        return []

    prs = []
    for p in data[:MAX_PRS]:
        try:
            prs.append({
                'number': p['number'],
                'title': p['title'],
                'state': p['state'],
                'user': p['user']['login'],
                'created_at': p['created_at']
            })
        except:
            continue

    return prs

def fetch_repo_info(repo_info, github_token):
    """Fetch repository metadata."""
    data = github_api_request(repo_info['api_url'], github_token)

    if not data:
        return {}

    return {
        'name': data.get('name', ''),
        'description': data.get('description', ''),
        'language': data.get('language', ''),
        'stars': data.get('stargazers_count', 0),
        'forks': data.get('forks_count', 0)
    }

# -----------------------------
# Repository Processing
# -----------------------------

def process_repository(repo_url, github_token):
    """Clone repo, parse code, store in SQLite, and return analysis."""
    print(f"\n{'='*60}")
    print(f"PROCESSING: {repo_url}")
    print(f"{'='*60}\n")

    try:
        repo_info = extract_repo_info(repo_url)
    except Exception as e:
        print(f"ERROR extracting repo info: {e}")
        raise

    # Create temp database
    db_path = f"/tmp/lineage_{repo_info['owner']}_{repo_info['repo']}.db"
    print(f"Database path: {db_path}")

    try:
        conn = init_db(db_path)
        print("✓ Database initialized")
    except Exception as e:
        print(f"ERROR initializing database: {e}")
        raise

    try:
        # Fetch metadata
        print("Fetching repository metadata...")
        repo_details = fetch_repo_info(repo_info, github_token)
        commits = fetch_commits(repo_info, github_token)
        prs = fetch_pull_requests(repo_info, github_token)

        print(f"✓ Fetched: {len(commits)} commits, {len(prs)} PRs")

        # Store commits in DB
        for commit in commits:
            try:
                insert_commit(conn, commit['sha'], commit['author'], commit['email'],
                             commit['message'], commit['date'])
            except Exception as e:
                print(f"Warning: Could not insert commit {commit['sha']}: {e}")

        conn.commit()

        # Clone and parse repository
        print("\nCloning repository...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_path = os.path.join(tmp_dir, "repo")

            # Check if git is available
            try:
                git_version = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=5)
                print(f"Git version: {git_version.stdout.strip()}")
            except FileNotFoundError:
                print("ERROR: Git not found in Lambda environment")
                # Return partial results without code parsing
                return {
                    'repo': repo_info['full_name'],
                    'details': repo_details,
                    'commits': commits,
                    'prs': prs,
                    'symbols': [],
                    'file_stats': [],
                    'stats': {
                        'commits_count': len(commits),
                        'prs_count': len(prs),
                        'functions_count': 0,
                        'classes_count': 0,
                        'files_count': 0
                    },
                    'warning': 'Git not available - code parsing skipped'
                }

            # Clone
            try:
                result = subprocess.run(
                    ['git', 'clone', '--depth', '1', repo_url, repo_path],
                    capture_output=True, text=True, timeout=90, check=True
                )
                print("✓ Repository cloned")
            except subprocess.TimeoutExpired:
                print("ERROR: Git clone timed out")
                raise Exception("Repository cloning timed out after 90 seconds")
            except subprocess.CalledProcessError as e:
                print(f"ERROR: Git clone failed: {e.stderr}")
                raise Exception(f"Git clone failed: {e.stderr}")

            # Get HEAD commit SHA
            try:
                head_sha = subprocess.run(
                    ['git', '-C', repo_path, 'rev-parse', 'HEAD'],
                    capture_output=True, text=True, check=True
                ).stdout.strip()
                print(f"HEAD commit: {head_sha[:8]}")
            except Exception as e:
                print(f"Warning: Could not get HEAD sha: {e}")
                head_sha = commits[0]['sha'] if commits else 'unknown'

            # Parse files
            file_count = 0
            symbol_count = 0

            print("\nParsing code files...")
            for root, dirs, files in os.walk(repo_path):
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv']]

                for filename in files:
                    if not filename.endswith(SUPPORTED_EXTENSIONS):
                        continue

                    full_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(full_path, repo_path)

                    try:
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()

                        symbols = parse_file(relative_path, content)

                        if symbols:
                            file_id = insert_file(conn, relative_path)

                            for kind, name, start, end in symbols:
                                insert_symbol(conn, file_id, head_sha, kind, name, start, end)
                                symbol_count += 1

                            file_count += 1
                            if file_count <= 10:  # Only print first 10
                                print(f"  ✓ {relative_path}: {len(symbols)} symbols")

                    except Exception as e:
                        print(f"  ✗ Error reading {relative_path}: {e}")

            conn.commit()
            print(f"\n✓ Parsed {file_count} files, {symbol_count} symbols")

        # Query database for results
        all_symbols = get_all_symbols(conn)
        file_stats = get_file_statistics(conn)

        # Build result
        result = {
            'repo': repo_info['full_name'],
            'details': repo_details,
            'commits': commits,
            'prs': prs,
            'symbols': [
                {
                    'file': s[0],
                    'kind': s[1],
                    'name': s[2],
                    'start_line': s[3],
                    'end_line': s[4]
                }
                for s in all_symbols[:200]  # Limit to 200 symbols
            ],
            'file_stats': [
                {'file': f[0], 'functions': f[1], 'classes': f[2]}
                for f in file_stats[:50]
            ],
            'stats': {
                'commits_count': len(commits),
                'prs_count': len(prs),
                'functions_count': len([s for s in all_symbols if s[1] == 'function']),
                'classes_count': len([s for s in all_symbols if s[1] == 'class']),
                'files_count': len(file_stats)
            }
        }

        # Try to upload to S3 (optional)
        try:
            if S3_BUCKET and S3_BUCKET != 'git-lineage-data':
                s3_key = f"databases/{repo_info['owner']}/{repo_info['repo']}/lineage.db"
                s3.upload_file(db_path, S3_BUCKET, s3_key)
                result['s3_path'] = f"s3://{S3_BUCKET}/{s3_key}"
                print(f"✓ Database backed up to S3: {s3_key}")
        except Exception as e:
            print(f"Warning: Could not upload to S3: {e}")

        print(f"\n{'='*60}")
        print(f"COMPLETE: {symbol_count} symbols indexed")
        print(f"{'='*60}\n")

        return result

    except Exception as e:
        print(f"ERROR in process_repository: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        raise
    finally:
        try:
            conn.close()
        except:
            pass

def build_context(repo_data, query=None):
    """Build context for LLM from repository data."""
    context = []

    # Basic info
    context.append(f"Repository: {repo_data['repo']}")
    if repo_data['details'].get('description'):
        context.append(f"Description: {repo_data['details']['description']}")

    # Statistics
    stats = repo_data['stats']
    context.append(f"\nCodebase Statistics:")
    context.append(f"- Files: {stats['files_count']}")
    context.append(f"- Functions: {stats['functions_count']}")
    context.append(f"- Classes: {stats['classes_count']}")
    context.append(f"- Commits: {stats['commits_count']}")
    context.append(f"- Pull Requests: {stats['prs_count']}")

    # Code structure
    if repo_data.get('symbols'):
        context.append(f"\nCode Structure:")

        # Group by file
        by_file = {}
        for s in repo_data['symbols'][:100]:
            file = s['file']
            if file not in by_file:
                by_file[file] = {'functions': [], 'classes': []}

            # Add to appropriate list
            if s['kind'] == 'function':
                by_file[file]['functions'].append(s['name'])
            elif s['kind'] == 'class':
                by_file[file]['classes'].append(s['name'])

        for file, items in list(by_file.items())[:10]:
            context.append(f"\n{file}:")
            if items['functions']:
                context.append(f"  Functions: {', '.join(items['functions'][:10])}")
            if items['classes']:
                context.append(f"  Classes: {', '.join(items['classes'][:10])}")

    # Recent commits
    if repo_data.get('commits'):
        context.append(f"\nRecent Commits:")
        for c in repo_data['commits'][:5]:
            context.append(f"- {c['message'][:80]} (by {c['author']})")

    # Recent PRs
    if repo_data.get('prs'):
        context.append(f"\nRecent Pull Requests:")
        for p in repo_data['prs'][:5]:
            context.append(f"- PR #{p['number']}: {p['title'][:80]} ({p['state']})")

    return '\n'.join(context)

# -----------------------------
# Lambda Handler
# -----------------------------

def lambda_handler(event, context):
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "POST,OPTIONS"
    }

    if event.get('httpMethod') == 'OPTIONS':
        return {"statusCode": 200, "headers": headers, "body": ""}

    try:
        body = json.loads(event.get("body", "{}")) if isinstance(event.get("body"), str) else event
        action = body.get("action")

        if action == "process":
            repo_url = body.get("repo_url")
            if not repo_url:
                return {
                    "statusCode": 400,
                    "headers": headers,
                    "body": json.dumps({"error": "repo_url required"})
                }

            result = process_repository(repo_url, GITHUB_TOKEN)
            REPO_CACHE[repo_url] = result

            return {
                "statusCode": 200,
                "headers": headers,
                "body": json.dumps({
                    "message": "Repository processed",
                    "stats": result['stats']
                })
            }

        elif action == "ask":
            text = body.get("text", "")
            repo_url = body.get("repo_url", "")

            repo_data = REPO_CACHE.get(repo_url)
            if not repo_data:
                return {
                    "statusCode": 400,
                    "headers": headers,
                    "body": json.dumps({
                        "answer": "⚠️ Please analyze the repository first."
                    })
                }

            context = build_context(repo_data, text)

            prompt = f"""You are analyzing the GitHub repository: {repo_data['repo']}

Repository Context:
{context}

User Question: {text}

Provide a detailed answer based on the code structure, commits, and pull requests shown above."""

            response = bedrock.invoke_model(
                modelId=LLM_MODEL,
                contentType="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "messages": [{"role": "user", "content": prompt}]
                })
            )

            result = json.loads(response['body'].read())
            answer = result['content'][0]['text']

            return {
                "statusCode": 200,
                "headers": headers,
                "body": json.dumps({"answer": answer})
            }

        elif action == "get_data":
            repo_url = body.get("repo_url", "")
            repo_data = REPO_CACHE.get(repo_url)

            if not repo_data:
                return {
                    "statusCode": 404,
                    "headers": headers,
                    "body": json.dumps({"error": "Repository not found"})
                }

            return {
                "statusCode": 200,
                "headers": headers,
                "body": json.dumps(repo_data)
            }

        else:
            return {
                "statusCode": 400,
                "headers": headers,
                "body": json.dumps({"error": "Invalid action"})
            }

    except Exception as e:
        print(f"Error: {str(e)}")
        print(traceback.format_exc())

        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({"error": str(e), "type": type(e).__name__})
        }