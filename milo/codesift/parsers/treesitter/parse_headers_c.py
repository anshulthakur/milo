from tree_sitter_language_pack import get_parser
from tree_sitter import Node, Tree

def is_struct_defined(node):
    """
    Returns True if the struct_specifier has a body.
    """
    return any(child.type == 'field_declaration_list' for child in node.children)

def is_typedef_defined(node):
    """
    Returns True if the typedef wraps a defined struct or union.
    """
    for child in node.children:
        if child.type == 'type_descriptor':
            for grandchild in child.children:
                if grandchild.type == 'struct_specifier' and is_struct_defined(grandchild):
                    return True
    return False

def is_extern_declaration(node):
    """
    Returns True if the declaration has 'extern' storage class.
    """
    return any(child.type == 'storage_class_specifier' and child.text.decode() == 'extern'
               for child in node.children)

def get_doc_node(node, debug=False):
    """
    Returns the comment node preceding `node`, if it's adjacent.
    """
    siblings = node.parent.children if node.parent else []
    idx = siblings.index(node)
    if debug:
        print("Get documentation for", node.text.decode())
    doc_node = None
    for i in range(idx - 1, -1, -1):
        prev = siblings[i]
        if debug:
            print(prev.type)
            print(prev.text.decode())
        if prev.type == 'comment':
            doc_node = prev
            break
        elif prev.type in ('preproc_directive', 'declaration', 'function_definition'):
            break  # Stop if we hit non-comment code
        else:
            if debug:
                print("Not a comment, preproc or declaration or function_definition")
                print(f"Is {prev.type}")
            continue
    return doc_node

def collect_structs_and_typedefs(node, debug=False):
    """
    Recursively collects (doc_node, target_node) for struct_specifier and type_definition.
    """
    results = []
    for child in node.children:
        if child.type == 'declaration' and is_extern_declaration(child):
            continue  # Skip extern declarations

        if child.type == 'struct_specifier' and is_struct_defined(child):
            doc_node = get_doc_node(child, debug)
            if debug:
                if doc_node:
                    print("Found", doc_node)
                else:
                    print("No doc_node found")
            results.append((doc_node, child))

        elif child.type == 'type_definition' and is_typedef_defined(child):
            doc_node = get_doc_node(child, debug)
            if debug:
                if doc_node:
                    print("Found", doc_node)
                else:
                    print("No doc_node found")
            results.append((doc_node, child))

        else:
            results.extend(collect_structs_and_typedefs(child, debug))
    return results

def parse_c_headers(local_path, file_content):
    parser = get_parser('c')
    tree = parser.parse(file_content)
    root_node = tree.root_node
    pairs = collect_structs_and_typedefs(root_node)
    return pairs

def get_node_identifier(node):
    """
    Extracts the identifier name from a struct or typedef node.
    """
    if node.type == 'struct_specifier':
        for child in node.children:
            if child.type == 'type_identifier':
                return child.text.decode()
    elif node.type == 'type_definition':
        for child in node.children:
            if child.type == 'type_identifier':
                return child.text.decode()
    return None

def match_node_by_identity(pairs, old_node):
    """
    Matches a node in `pairs` by type and identifier name.
    """
    old_type = old_node.type
    old_name = get_node_identifier(old_node)

    print(f"find {old_name}")
    for doc_node, target_node in pairs:
        if target_node.type != old_type:
            continue
        new_name = get_node_identifier(target_node)
        if new_name == old_name:
            return doc_node, target_node
    return None, None

def update_header_docstring(local_path, programming_language, old_node, new_block):
    from pathlib import Path

    # Read current source
    raw_bytes = Path(local_path).read_bytes()
    parser = get_parser(programming_language.value)
    tree = parser.parse(raw_bytes)
    root_node = tree.root_node

    # Recollect struct/typedef pairs
    pairs = collect_structs_and_typedefs(root_node, debug=True)

    # Match node
    doc_node, target_node = match_node_by_identity(pairs, old_node)

    if not target_node:
        print(f"Could not match node: {get_node_identifier(old_node)}")
        raise ValueError("Matching node not found in updated tree.")
    if not doc_node:
        print("doc_node not found")
        
    # Determine replacement range
    start_byte = doc_node.start_byte if doc_node else target_node.start_byte
    end_byte = target_node.end_byte

    # Check for trailing semicolon in original source
    has_trailing_semicolon = (
        end_byte < len(raw_bytes) and raw_bytes[end_byte:end_byte+1] == b';'
    )

    # Encode new block
    new_block_bytes = new_block.encode("utf-8")

    # Replace logic
    if new_block_bytes.endswith(b';') and has_trailing_semicolon:
        updated_bytes = (
            raw_bytes[:start_byte] +
            new_block_bytes +
            raw_bytes[end_byte+1:]
        )
    else:
        updated_bytes = (
            raw_bytes[:start_byte] +
            new_block_bytes +
            raw_bytes[end_byte:]
        )

    # Decode and write back
    updated_source = updated_bytes.decode("utf-8", errors="replace")
    Path(local_path).write_text(updated_source, encoding="utf-8")
    
    return
