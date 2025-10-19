import os
from typing import List, Tuple
from tree_sitter_languages import get_language, get_parser


# Returns: [(kind, name, start_line, end_line)] where kind ∈ {"function","class"}
def parse_symbols(file_path: str) -> List[Tuple[str, str, int, int]]:
    if os.path.splitext(file_path)[1].lower() not in (".py", ".pyi"):
        return []

    try:
        language = get_language("python")
        parser = get_parser("python")
    except Exception:
        print("could not get language/parser")
        return []

    try:
        with open(file_path, "rb") as f:
            src = f.read()
    except Exception:
        print("could not open file")
        return []

    tree = parser.parse(src)
    print("parsed tree")
    print(tree)
    root = tree.root_node

    def text(n) -> str:
        return src[n.start_byte : n.end_byte].decode("utf-8", "replace")

    def lines(n) -> Tuple[int, int]:
        # Tree-sitter is 0-based; convert to 1-based line numbers
        return n.start_point[0] + 1, n.end_point[0] + 1

    # Climb to the def/class node; if wrapped by decorators, expand span to include them
    def span_node_for_identifier(id_node):
        # climb until function_definition or class_definition
        n = id_node.parent
        while n and n.type not in ("function_definition", "class_definition"):
            n = n.parent
        if not n:
            return id_node  # fallback (shouldn't happen for valid code)
        # include decorators if present
        if n.parent and n.parent.type == "decorated_definition":
            return n.parent
        return n

    # One query covers plain + decorated defs
    q = language.query(r"""
      (function_definition name: (identifier) @fname)
      (class_definition    name: (identifier) @cname)
      (decorated_definition
        (decorator)+
        definition: (function_definition name: (identifier) @dfname))
      (decorated_definition
        (decorator)+
        definition: (class_definition    name: (identifier) @dcname))
    """)

    results: List[Tuple[str, str, int, int]] = []
    for node, capname in q.captures(root):
        print(node)
        if capname in ("fname", "dfname"):
            span_node = span_node_for_identifier(node)
            s, e = lines(span_node)
            results.append(("function", text(node), s, e))
        elif capname in ("cname", "dcname"):
            span_node = span_node_for_identifier(node)
            s, e = lines(span_node)
            results.append(("class", text(node), s, e))

    return results
