#!/usr/bin/env python3
import os
import sqlite3
import subprocess
from git import Repo
from datetime import datetime
from tree_sitter_languages import get_parser
from parser import parse_symbols

DB_PATH = "lineage.db"


def find_git_root(start_path="."):
    path = os.path.abspath(start_path)
    while path != "/":
        if os.path.isdir(os.path.join(path, ".git")):
            return path
        path = os.path.dirname(path)
    raise RuntimeError("No .git directory found in parent paths")


REPO_PATH = find_git_root()
repo = Repo(REPO_PATH)

# --- Database helpers -------------------------------------------------------


def connect_db():
    return sqlite3.connect(DB_PATH)


def init_db(conn):
    with open("schema.sql") as f:
        conn.executescript(f.read())
    conn.commit()


# --- Insert helpers ---------------------------------------------------------


def insert_commit(conn, commit):
    conn.execute(
        """
        INSERT OR IGNORE INTO commits
        (commit_sha, author_name, author_email, message, committed_at)
        VALUES (?, ?, ?, ?, ?)
    """,
        (
            commit.hexsha,
            commit.author.name,
            commit.author.email,
            commit.message.strip(),
            datetime.fromtimestamp(commit.committed_date).isoformat(),
        ),
    )


def insert_file(conn, path):
    conn.execute(
        """
        INSERT OR IGNORE INTO files (current_path)
        VALUES (?)
    """,
        (path,),
    )
    return conn.execute(
        "SELECT file_id FROM files WHERE current_path = ?", (path,)
    ).fetchone()[0]


def insert_symbol(conn, file_id, commit_sha, kind, name, start_line, end_line):
    """Insert one symbol; safe to call many times."""
    conn.execute(
        """
        INSERT INTO symbols (file_id, commit_sha, kind, name, start_line, end_line)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (file_id, commit_sha, kind, name, start_line, end_line),
    )


# --- Main indexing routine --------------------------------------------------


def index_head(conn):
    head_commit = repo.head.commit
    print(f"Indexing commit {head_commit.hexsha[:8]} {head_commit.summary}")
    insert_commit(conn, head_commit)

    tree = head_commit.tree
    for blob in tree.traverse():
        if blob.type != "blob" or blob.path.startswith(".git"):
            continue
        if not blob.path.endswith((".py", ".js", ".ts", ".java", ".go", ".cpp", ".c")):
            continue

        print(f"  parsing {blob.path}")
        file_id = insert_file(conn, blob.path)
        abs_path = os.path.join(REPO_PATH, blob.path)
        print(abs_path)
        for kind, name, start, end in parse_symbols(abs_path):
            insert_symbol(conn, file_id, head_commit.hexsha, kind, name, start, end)

    conn.commit()
    print("✅ done.")


# --- Entrypoint -------------------------------------------------------------

if __name__ == "__main__":
    conn = connect_db()
    if not os.path.exists("schema.sql"):
        print("schema.sql not found. Please create it with the DDL below.")
        exit(1)
    init_db(conn)
    index_head(conn)
    conn.close()
