import sqlite3

DB_PATH = "lineage.db"

def connect_db():
    return sqlite3.connect(DB_PATH)

def search_symbols_by_name(name: str):
    conn = connect_db()
    cursor = conn.execute("""
        SELECT f.current_path, s.kind, s.name, s.start_line, s.end_line
        FROM symbols s
        JOIN files f ON s.file_id = f.file_id
        WHERE s.name LIKE ?
        ORDER BY f.current_path;
    """, (f"%{name}%",))
    results = cursor.fetchall()
    conn.close()
    return results

def list_files_with_most_functions(limit=10):
    conn = connect_db()
    cursor = conn.execute("""
        SELECT f.current_path, COUNT(*) AS func_count
        FROM symbols s
        JOIN files f ON s.file_id = f.file_id
        WHERE s.kind='function'
        GROUP BY f.current_path
        ORDER BY func_count DESC
        LIMIT ?;
    """, (limit,))
    results = cursor.fetchall()
    conn.close()
    return results
