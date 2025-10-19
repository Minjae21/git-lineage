import os
import json
import tempfile
import subprocess
import ast
import re

# supported languages and their file extensions:
LANGUAGE_EXTENSIONS = {
    "python": [".py"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx"],
}

def detect_language(filename):
    """Detect the programming language based on file extension."""
    for lang, exts in LANGUAGE_EXTENSIONS.items():
        if any(filename.endswith(ext) for ext in exts):
            return lang
    return None

def parse_python_with_ast(source_code, filepath):
    """Parse Python code using built-in AST module."""
    try:
        tree = ast.parse(source_code)
        extracted = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # function source lines
                start_line = node.lineno
                end_line = node.end_lineno or start_line
                code_lines = source_code.split('\n')[start_line-1:end_line]
                code_snippet = '\n'.join(code_lines)

                # extract docstring
                docstring = ast.get_docstring(node) or ""

                extracted.append({
                    "type": "function",
                    "name": node.name,
                    "language": "python",
                    "path": filepath,
                    "class_context": None,
                    "docstring": docstring,
                    "code": code_snippet,
                    "start_line": start_line,
                    "end_line": end_line,
                    "node_type": "function_definition"
                })

            elif isinstance(node, ast.ClassDef):
                start_line = node.lineno
                end_line = node.end_lineno or start_line
                code_lines = source_code.split('\n')[start_line-1:end_line]
                code_snippet = '\n'.join(code_lines)

                docstring = ast.get_docstring(node) or ""

                extracted.append({
                    "type": "class",
                    "name": node.name,
                    "language": "python",
                    "path": filepath,
                    "class_context": None,
                    "docstring": docstring,
                    "code": code_snippet,
                    "start_line": start_line,
                    "end_line": end_line,
                    "node_type": "class_definition"
                })

        return extracted

    except SyntaxError as e:
        print(f"⚠️ Syntax error in {filepath}: {e}")
        return []

def parse_js_ts_with_regex(source_code, filepath, language):
    """Parse JavaScript/TypeScript code using regex patterns."""
    extracted = []
    lines = source_code.split('\n')

    patterns = {
        'function': [
            r'function\s+(\w+)\s*\(',
            r'(\w+)\s*:\s*function\s*\(',
            r'(\w+)\s*=\s*function\s*\(',
            r'(\w+)\s*=\s*\([^)]*\)\s*=>',
            r'(\w+)\s*\([^)]*\)\s*=>',
        ],
        'class': [
            r'class\s+(\w+)',
            r'interface\s+(\w+)',
            r'type\s+(\w+)\s*=',
            r'enum\s+(\w+)',
        ],
        'method': [
            r'(\w+)\s*\([^)]*\)\s*{',
            r'(\w+)\s*:\s*\([^)]*\)\s*=>',
        ]
    }

    for i, line in enumerate(lines, 1):
        line_stripped = line.strip()

        if not line_stripped or line_stripped.startswith('//') or line_stripped.startswith('/*'):
            continue

        # checking for functions
        for pattern in patterns['function']:
            match = re.search(pattern, line)
            if match:
                name = match.group(1)
                if name and name not in ['if', 'for', 'while', 'switch', 'catch']:
                    end_line = find_block_end(lines, i-1)
                    code_snippet = '\n'.join(lines[i-1:end_line])

                    extracted.append({
                        "type": "function",
                        "name": name,
                        "language": language,
                        "path": filepath,
                        "class_context": None,
                        "docstring": "",
                        "code": code_snippet,
                        "start_line": i,
                        "end_line": end_line,
                        "node_type": "function_declaration"
                    })
                    break

        # checking for classes/interfaces
        for pattern in patterns['class']:
            match = re.search(pattern, line)
            if match:
                name = match.group(1)
                if name:
                    end_line = find_block_end(lines, i-1)
                    code_snippet = '\n'.join(lines[i-1:end_line])

                    entity_type = "class"
                    if "interface" in line:
                        entity_type = "interface"
                    elif "type" in line:
                        entity_type = "type"
                    elif "enum" in line:
                        entity_type = "enum"

                    extracted.append({
                        "type": entity_type,
                        "name": name,
                        "language": language,
                        "path": filepath,
                        "class_context": None,
                        "docstring": "",
                        "code": code_snippet,
                        "start_line": i,
                        "end_line": end_line,
                        "node_type": "class_declaration"
                    })
                    break

    return extracted

def find_block_end(lines, start_idx):
    """Find the end of a code block (simplified)."""
    brace_count = 0
    in_block = False

    for i in range(start_idx, len(lines)):
        line = lines[i]
        for char in line:
            if char == '{':
                brace_count += 1
                in_block = True
            elif char == '}':
                brace_count -= 1
                if in_block and brace_count == 0:
                    return i + 1

    return len(lines)

def parse_code_file(filepath):
    """Parse a single code file and extract functions, methods, classes, and other structures."""
    language = detect_language(filepath)
    if not language:
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception as e:
        print(f"⚠️ Could not read file {filepath}: {e}")
        return []

    try:
        if language == "python":
            return parse_python_with_ast(source_code, filepath)
        elif language in ["javascript", "typescript"]:
            return parse_js_ts_with_regex(source_code, filepath, language)
        else:
            return []
    except Exception as e:
        print(f"⚠️ Could not parse {filepath}: {e}")
        return []

def parse_repository_from_url(repo_url, output_path="data/functions.json"):
    """
    Clone GitHub repo, parse supported code files, save JSON, and remove repo to save space.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_path = os.path.join(tmp_dir, "repo")
        print(f"Cloning {repo_url} ...")
        try:
            subprocess.run(['git', 'clone', '--depth', '1', repo_url, repo_path],
                         check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to clone repository: {e}")
            return []

        print(f"✅ Repository cloned into {repo_path}")

        all_items = []
        file_count = 0

        for root, _, files in os.walk(repo_path):
            if any(skip in root for skip in ['.git', 'node_modules', '__pycache__', 'venv', 'dist', 'build']):
                continue

            for file in files:
                if detect_language(file):
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, repo_path)
                    file_count += 1
                    print(f"Parsing {relative_path} ...")
                    try:
                        items = parse_code_file(full_path)
                        for item in items:
                            item['path'] = relative_path
                        all_items.extend(items)
                        print(f"  ✓ Found {len(items)} entities")
                    except Exception as e:
                        print(f"  ❌ Failed to parse {file}: {e}")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_items, f, indent=2)

        print(f"\n✅ Parsed {file_count} files")
        print(f"✅ Extracted {len(all_items)} code entities saved to {output_path}")

        type_counts = {}
        for item in all_items:
            type_counts[item['type']] = type_counts.get(item['type'], 0) + 1

        if type_counts:
            print("\n Summary by type:")
            for entity_type, count in sorted(type_counts.items()):
                print(f"  {entity_type}: {count}")
        else:
            print("\n No code entities were extracted.")

    return all_items

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Parse GitHub repo URL")
    parser.add_argument("--url", required=True, help="GitHub repo URL")
    parser.add_argument("--out", default="data/functions.json", help="Output JSON path")
    args = parser.parse_args()

    parse_repository_from_url(args.url, args.out)