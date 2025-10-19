-- Commits
CREATE TABLE IF NOT EXISTS commits (
  commit_sha   TEXT PRIMARY KEY,
  author_name  TEXT,
  author_email TEXT,
  message      TEXT,
  committed_at DATETIME
);

-- Files
CREATE TABLE IF NOT EXISTS files (
  file_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  current_path TEXT NOT NULL UNIQUE
);

-- Symbols
CREATE TABLE IF NOT EXISTS symbols (
  symbol_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id      INTEGER NOT NULL,
  commit_sha   TEXT NOT NULL,
  kind         TEXT CHECK (kind IN ('function','class')),
  name         TEXT NOT NULL,
  start_line   INTEGER,
  end_line     INTEGER,
  FOREIGN KEY (file_id) REFERENCES files(file_id),
  FOREIGN KEY (commit_sha) REFERENCES commits(commit_sha)
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_symbols_file_commit ON symbols (file_id, commit_sha);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols (name);
