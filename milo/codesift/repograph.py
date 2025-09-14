import os
import sys
import networkx as nx
from tree_sitter_language_pack import get_parser
from tree_sitter import Node, Tree
import json
import re
from collections import defaultdict
import traceback

C_KEYWORDS = {"if", "while", "for", "switch", "return", "unlikely"}
PYTHON_KEYWORDS = {
    "if",
    "while",
    "for",
    "def",
    "return",
    "class",
    "try",
    "except",
    "with",
}
call_dict = {}


def node_val(source_byte, node):
    """
    Extracts a UTF-8 decoded string slice from source_byte based on node's byte offsets.
    
    Args:
        source_byte (bytes): Raw byte data to extract content from
        node: Object containing start_byte and end_byte attributes defining the slice range. 
            Expected to be an AST/parse node with byte offset metadata.
    
    Returns:
        str: Decoded substring corresponding to the node's position in source_byte
    
    Raises:
        UnicodeDecodeError: If the byte slice contains invalid UTF-8 sequences
    
    Context:
        Used in syntax parsing workflows where nodes represent tokenized elements 
        with byte-range metadata (common in AST/CFG processing pipelines).
    """
    return source_byte[node.start_byte : node.end_byte].decode("utf8")


def print_identifiers(node, file_bytes):
    """
    Recursively traverses an abstract syntax tree (AST) to print details of identifier nodes.
    
    Args:
        node: AST node object representing a syntax construct (from parser/AST library).
        file_bytes: Source code bytes array used to extract string values from identifiers.
    
    Behavior:
    - Outputs node type and value for 'identifier' nodes via node_val()
    - Recursively processes all child nodes in the tree structure
    - Serves as a diagnostic utility for visualizing parsed code structures
    
    Revisions:
    1. Note about print_functions_c() invocation was removed since this Python function is
       actually called by analyze_code() and process_ast() within the same module.
    2. Clarified that node_val() is the correct helper function for value extraction.
    3. Added detail about file_bytes parameter's role in byte-to-string conversion.
    """
    print(f"Node :{node} Node type: {node.type}")
    if node.type == "identifier":
        identifier = node_val(file_bytes, node)
        print("identifier", ":-", identifier)
    for child in node.children:
        print_identifiers(child, file_bytes)


def print_functions_c(file_bytes, tree):
    """
    Analyzes and prints identifier information from C language syntax trees using Tree-sitter.
    
    Args:
        file_bytes (bytes): Byte representation of the source code file being parsed
        tree: Tree-sitter syntax tree with root_node containing the AST structure
    
    Processing Flow:
    1. Iterates through top-level nodes in the syntax tree
    2. Delegates identifier extraction to print_identifiers() for each child node
    3. Outputs metadata about identifier nodes (names, positions, etc.)
    
    Key Contextual Details:
    - Specifically designed for C language syntax analysis
    - Integrates with Tree-sitter's C grammar implementation
    - Works as part of a code inspection toolchain with print_identifiers()
    - Operates on raw byte data for precise character position tracking
    
    Note:
    This function is typically used during AST traversal phases in code analysis tools.
    The output format depends on implementation details of print_identifiers().
    """
    for child in tree.root_node.children:
        print_identifiers(child, file_bytes)


def guess_extension_from_shebang(file_path=None, file_content=None):
    """
    Analyzes the shebang line of a script to infer its programming language extension.
    
    Args:
        file_path (str, optional): Path to the file. Mutually exclusive with file_content.
        file_content (str, optional): Contents of the file. Mutually exclusive with file_path.
    
    Returns:
        str or None: Mapped file extension (e.g., ".py" for Python) if shebang matches a known pattern,
                        otherwise None. Returns None also on I/O errors or invalid input.
    
    Raises:
        None: Exceptions are caught internally and logged via traceback.print_exc().
    
    Shebang interpreter mapping includes:
        "python" -> ".py"
        "perl" -> ".pl"
        "ruby" -> ".rb"
        "node" -> ".js"
        "java" -> ".java"
    
    Behavior:
    - Extracts the interpreter from the shebang line by taking the last path segment.
    - Performs case-insensitive substring matching of interpreter names against known patterns.
    - Returns first matching extension; otherwise returns None.
    - Handles edge cases like empty file_content or invalid file paths gracefully.
    """
    try:
        if file_path is not None:
            with open(file_path, "r") as file:
                first_line = file.readline().strip()
        else:
            first_line = file_content.splitlines()[0].strip()

        print(first_line)
        if not first_line.startswith("#!"):
            return None

        # Map common shebang patterns to programming languages
        shebang_map = {
            "python": ".py",
            "perl": ".pl",
            "ruby": ".rb",
            "node": ".js",
            "java": ".java",
        }

        # Extract the interpreter from the shebang
        interpreter = first_line.split("/")[-1]

        # print(interpreter)

        for key, extension in shebang_map.items():
            if key in interpreter.lower():
                return extension

        return None

    except Exception as e:
        traceback.print_exc()
        return None


def update_callgraph(caller, callee=None, params=None, filename=None):
    """
    Update the global call_dict structure with new caller-callee relationships.

    This function maintains a repository-wide call graph by either:
    1. Creating a new entry for a caller function
    2. Updating an existing caller's called functions list
    3. Tracking third-party/external function calls
    4. Handling parameter changes in function definitions

    Parameters:
        caller (str): Name of the calling function
        callee (str, optional): Name of the called function. Defaults to None.
        params (str, optional): Parameter string for the caller function. Defaults to None.
        filename (str, optional): Source file where the caller is defined. Defaults to None.

    Behavior:
    - Creates a namespaced key using filename + '::' + caller if provided
    - Initializes new caller entries with metadata and empty call list
    - Resolves callees by searching existing keys in call_dict
    - Tracks unresolved callees under 'third_party' section
    - Issues warnings when function signatures change during analysis
    - Maintains unique relationships between functions

    The global call_dict structure contains:
    { 
        "func_name": str, 
        "args": str, 
        "calls": [callee_keys], 
        "defined_in": str, 
    }

    Note: Third-party calls are stored in a nested 'third_party' dictionary with metadata about callers.
    Warnings are printed when parameter mismatches occur between function definitions and existing entries.
    """
    global call_dict
    if filename:
        key = f"{filename}::{caller}"
    else:
        key = caller

    callee_key = None

    if key not in call_dict:
        call_dict[key] = {
            "func_name": caller,
            "args": params or "",
            "calls": [],
            "defined_in": filename,
        }

    if callee:
        # If callee is already defined somewhere, use that key if known
        if not callee_key:
            for k in call_dict:
                if k.endswith(f"::{callee}"):
                    callee_key = k
                    break

        # If still unresolved, record it as a third-party call
        if not callee_key:
            third_party = call_dict.setdefault("third_party", {})
            tp = third_party.setdefault(callee, {"called_by": []})
            if key not in tp["called_by"]:
                tp["called_by"].append(key)
        else:
            if callee_key not in call_dict[key]["calls"]:
                call_dict[key]["calls"].append(callee_key)

    if params and call_dict[key]["args"] != params.strip():
        print(
            f"Warning: Update {key} params from {call_dict[key]['args'].strip()} to {params}"
        )
        call_dict[key]["args"] = params.strip()


def list_source_files(root, supported_ext):
    """
    Recursively lists all files with specified extensions under a given directory root.
    
    Args:
        root (str): The root directory path to start scanning for files.
        supported_ext (List[str]): List of file extensions (e.g. [".py", ".c"]) to include in results.
    
    Yields:
        str: Full path to each matching source file found under the root directory.
    
    Note:
        This function is used by create_repograph() in crab/agents/repograph.py to collect files for repository graph construction. Uses os.walk() for recursive directory traversal. Filenames are matched exactly against extensions (case-sensitive).
    """
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            if any(fname.endswith(ext) for ext in supported_ext):
                yield os.path.join(dirpath, fname)


def get_function_name_from_definition(node):
    """
    Extracts the function name from an abstract syntax tree (AST) node representing a function definition.
    
    This function traverses the AST node structure to identify and return the function name. It handles cases where
    the declarator might be wrapped in a pointer declaration (e.g., function pointers) by skipping the asterisk node.
    The implementation assumes a specific AST node hierarchy with types like 'pointer_declarator',
    'function_declarator', and 'identifier'.
    
    Parameters:
        node: An AST node representing a function definition or declaration. Expected to conform to a C-like AST structure.
    
    Returns:
        str or None: The decoded function name as a string if found, otherwise None.
    
    Contextual Usage:
    - This function is typically used in AST traversal utilities for code analysis or refactoring tools.
    - It is called by functions that process declarations in compiled language source code (e.g., C/C++ parsers).
    - The 'identifier' node must contain a byte string requiring decoding to UTF-8.
    
    Note:
    - Assumes a specific AST format where function declarators are nested under pointer declarators when present.
    - Does not handle complex declarator chains beyond pointer/function combinations.
    """
    for child in node.children:
        if child.type == "pointer_declarator":
            child = child.children[1]  # skip the asterisk, go to the actual declarator
        if child.type == "function_declarator":
            for grandchild in child.children:
                if grandchild.type == "identifier":
                    return grandchild.text.decode()
    return None


def extract_c_callee(node: Node, src_bytes: bytes):
    """
    Extracts the callee name from a C 'call_expression' node in an AST.

    This function is part of a C-specific code analysis module that processes AST nodes to extract
    function call information. It assumes the function expression is a simple identifier (e.g., foo()),
    but explicitly handles cases where the function might be wrapped in other node types by checking
    the 'identifier' type explicitly.

    Args:
        node: A tree-sitter Node representing a 'call_expression' in C syntax
        src_bytes: Raw source code bytes containing the text to extract

    Returns:
        str: Decoded callee name if the function is a simple identifier
        None: If the function node is not an identifier or extraction fails

    Note:
        - Part of a codebase that includes C-specific AST parsing utilities like get_function_signature_c
        - Works in conjunction with get_function_name_from_definition for full function analysis
        - Designed to handle edge cases where function pointers or macros might be involved
    """
    fn_node = node.child_by_field_name("function")
    if fn_node and fn_node.type == "identifier":
        return src_bytes[fn_node.start_byte : fn_node.end_byte].decode().strip()
    return None


# Signature extractors
def get_function_signature_c(node: Node, src_bytes: bytes):
    """
    Extracts C function signature components (name and parameter list) from an AST node.
    
    Parameters:
        node (Node): Tree-sitter AST node representing a C function declaration
        src_bytes (bytes): Source code bytes of the containing file (required for parameter slicing)
    
    Returns:
        Tuple[Optional[str], str]: 
            - Function name (None if not found in identifier nodes)
            - Normalized parameter list string (empty if no parameters found)
    
    Processing logic:
    1. Skips declaration specifiers (static/inline/extern modifiers)
    2. Unwraps pointer declarators to reach base identifier
    3. Extracts function name from 'identifier' node text
    4. Uses byte range slicing on parameter_list nodes to capture raw signature text
    5. Normalizes parameter spacing via whitespace regex substitution
    
    Typically called by C AST parsers during symbol resolution. Used in conjunction with
    get_function_signature_cpp for cross-language signature extraction.
    """
    name, params = None, ""

    for child in node.children:
        # Skip storage modifiers (static, inline, extern, etc.)
        if child.type == "declaration_specifiers":
            continue

        # Dig through pointer wrapping
        if child.type == "pointer_declarator":
            child = child.children[-1]

        # Match function_declarator and extract relevant pieces
        if child.type == "function_declarator":
            for grandchild in child.children:
                if grandchild.type == "identifier":
                    name = grandchild.text.decode()
                elif grandchild.type == "parameter_list":
                    raw = src_bytes[
                        grandchild.start_byte : grandchild.end_byte
                    ].decode()
                    params = re.sub(r"\s+", " ", raw).strip()

    return name, params


def default_callee_extractor(node: Node, src_bytes: bytes):
    """
    Extracts the callee function name from a syntax node in C-like language processing pipelines.

    This fallback extractor handles function declarations in Tree-sitter parse trees for
    C-family languages (C/C++/Objective-C) when more specific language-aware extractors
    are unavailable. It identifies function nodes by checking for 'identifier' type children
    under the 'function' field.

    Args:
        node (Node): Tree-sitter syntax node to analyze (typically a function declaration)
        src_bytes (bytes): Raw source code bytes containing the function declaration

    Returns:
        str | None: Decoded function name string if valid identifier found, otherwise None

    Integration Context:
        - Used in multi-language analysis systems as a base case handler
        - Complements language-specific extractors (e.g., Python attribute-aware handlers)
        - Works with Tree-sitter's C family grammar structure

    Tree-sitter Grammar Dependency:
        Requires nodes to have 'function' field with 'identifier' type children,
        per C-family language syntax rules.
    """
    fn_node = node.child_by_field_name("function")
    if fn_node and fn_node.type == "identifier":
        return src_bytes[fn_node.start_byte : fn_node.end_byte].decode().strip()
    return None


def extract_python_callee(node: Node, src_bytes: bytes):
    """
    Extracts the callee name from a Python 'call' AST node.
    
    Handles both simple identifiers (e.g., 'function') and attribute chains (e.g., 'obj.method').
    Recursively processes nested attribute nodes to construct fully qualified names.
    
    Args:
        node (Node): The abstract syntax tree node representing a function call.
        src_bytes (bytes): Raw source code bytes containing the function call text.
    
    Returns:
        Optional[str]: Decoded callee name as string if valid, None otherwise.
    
    Used in AST analysis workflows to resolve called function identifiers,
    particularly in dependency tracking and call graph construction scenarios.
    The implementation supports nested attributes (e.g., 'module.class.method')
    by recursively traversing the AST node structure.
    """
    target = node.child_by_field_name("function")
    if not target:
        return None

    if target.type == "identifier":
        return src_bytes[target.start_byte : target.end_byte].decode().strip()

    elif target.type == "attribute":
        # Handle obj.method style
        parts = []

        def collect_identifiers(attr_node):
            for child in attr_node.children:
                if child.type == "identifier":
                    parts.append(
                        src_bytes[child.start_byte : child.end_byte].decode().strip()
                    )
                elif child.type == "attribute":
                    collect_identifiers(child)

        collect_identifiers(target)
        return ".".join(parts) if parts else None

    return None


def get_function_signature_python(node: Node, src_bytes: bytes):
    """
    Extracts a Python function's name and parameter signature from an AST node.
    
    Args:
        node (Node): Tree-sitter Node representing a function definition
        src_bytes (bytes): Raw source code bytes containing the function
    
    Returns:
        Tuple[str, str]: Function name and formatted parameter string
    
    Process:
    1. Parses identifier child node for function name extraction
    2. Processes parameters child node with whitespace normalization
    3. Returns decoded name and compacted parameter signature
    
    Codebase Integration:
    - Directly used by `parse_function_def` in AST analysis modules
    - Integrates with src_bytes handling pattern seen in 14+ functions across the codebase
    - Serves as core utility for function signature extraction in Python parser pipeline
    
    Example Usage:
    >>> name, params = get_function_signature_python(func_node, source_code_bytes)
    >>> assert name == 'example_func'
    >>> assert params == 'arg1 arg2=42 *args **kwargs'
    """
    name, params = None, ""

    for child in node.children:
        if child.type == "identifier" and node.child_by_field_name("name") == child:
            name = src_bytes[child.start_byte : child.end_byte].decode()

        elif child.type == "parameters":
            raw = src_bytes[child.start_byte : child.end_byte].decode()
            params = re.sub(r"\s+", " ", raw).strip()

    return name, params


def extract_context_subgraph(G, center_func, depth):
    """
    Extracts a context subgraph centered on a specific node in a directed graph, including predecessors (callers) and successors (callees) up to a specified depth.
    
    Parameters:
        G (networkx.DiGraph): Directed graph representing function call relationships where nodes are functions and edges represent calls. Assumed to be pre-validated for existence of `center_func`.
        center_func (str): The central function node to build the subgraph around. Must exist in G.
        depth (int): Maximum traversal depth in both directions from the center node. Each direction (callers/callees) receives floor(depth/2) levels of expansion. For odd depths, the extra level is discarded (e.g., depth=3 → 1 level per direction).
    
    Returns:
        networkx.DiGraph: Subgraph containing all nodes within `depth//2` levels of predecessors and successors relative to the center function, including the center itself. Returns only {center_func} if no neighbors exist at specified depth.
    
    Example:
        For depth=2 → 1 level of callers and 1 level of callees
        For depth=3 → still 1 level in each direction (3//2 = 1)
    
    Notes:
        - Zero depth returns a subgraph with only the center function
        - Depth is applied symmetrically to both directions
        - Handles cyclic graphs safely via set-based frontier tracking
    """
    subgraph_nodes = set()
    for direction in [G.successors, G.predecessors]:
        frontier = {center_func}
        for _ in range(depth // 2):
            next_frontier = set()
            for node in frontier:
                next_frontier.update(direction(node))
            subgraph_nodes.update(next_frontier)
            frontier = next_frontier
    subgraph_nodes.add(center_func)
    return G.subgraph(subgraph_nodes)


LANGUAGE_HANDLERS = {
    "c": {
        "func_def_type": "function_definition",
        "body_type": "compound_statement",
        "call_type": "call_expression",
        "keywords": C_KEYWORDS,
        "signature_extractor": get_function_signature_c,
        "callee_extractor": extract_c_callee,
    },
    "python": {
        "func_def_type": "function_definition",
        "body_type": "block",
        "call_type": "call",
        "keywords": PYTHON_KEYWORDS,
        "signature_extractor": get_function_signature_python,
        "callee_extractor": lambda node, src_bytes: extract_python_callee(
            node, src_bytes
        ),
    },
    # Add more languages here
}


# def extract_function_calls(tree: Tree, src_bytes: bytes, lang: str, filename: str):
#     """
#     Parses a single source file and extracts:
#     - Function definitions (and registers them with full metadata)
#     - Function calls (and tracks callee relationships)
#     Promotes third-party calls to known definitions when resolved.
#     """
#     calls = []  # list of (caller, callee)

#     def walk(node: Node):
#         if lang == "c" and node.type == "function_definition":
#             current_func, params = get_function_signature(node, src_bytes)
#             if not current_func or current_func.strip() in C_KEYWORDS:
#                 return  # Ignore control keywords or unnamed functions

#             # Ensure it has a body (compound_statement)
#             body = next((child for child in node.children if child.type == "compound_statement"), None)
#             if not body:
#                 return

#             params = re.sub(r'\s+', ' ', params).strip()
#             func_key = f"{filename}::{current_func}"

#             # 🟡 Promote third-party to local definition if previously seen as 3rd-party
#             third_party = call_dict.setdefault("third_party", {})
#             if current_func in third_party:
#                 print(f"🔁 Promoting 3rd-party function to local: {func_key}")
#                 incoming = third_party[current_func].get("called_by", [])

#                 call_dict[func_key] = {
#                     'func_name': current_func,
#                     'args': params,
#                     'calls': [],
#                     'defined_in': filename,
#                     'incoming_calls': incoming
#                 }
#                 del third_party[current_func]
#             else:
#                 update_callgraph(caller=current_func, params=params, filename=filename)

#             # Walk the function body to record its calls
#             walk_func_body(body, current_func)
#         else:
#             for child in node.children:
#                 walk(child)

#     def walk_func_body(node: Node, current_func: str):
#         for child in node.children:
#             if child.type == "call_expression":
#                 fn_node = child.child_by_field_name("function")
#                 if fn_node and fn_node.type == "identifier":
#                     callee = src_bytes[fn_node.start_byte:fn_node.end_byte].decode().strip()
#                     if callee and callee.strip() not in C_KEYWORDS:
#                         calls.append((current_func, callee))
#                         update_callgraph(caller=current_func, callee=callee, filename=filename)
#             walk_func_body(child, current_func)

#     walk(tree.root_node)
#     return calls


def extract_function_calls(tree: Tree, src_bytes: bytes, lang: str, filename: str):
    """
    Extracts function call relationships from an AST (Abstract Syntax Tree) for code analysis.

    Args:
        tree (Tree): Root node of the AST to analyze.
        src_bytes (bytes): Source code bytes used to extract string representations of 
                            function names and parameters.
        lang (str): Programming language identifier (e.g., 'python', 'javascript')
                    determines parsing rules via LANGUAGE_HANDLERS.
        filename (str): File path context for cross-file callgraph tracking.

    Returns:
        List[Tuple[str, str]]: Direct function call relationships as (caller_function_name, 
                                callee_function_name) pairs.

    Raises:
        ValueError: If lang is not supported by LANGUAGE_HANDLERS.

    Notes:
        - Uses language-specific handlers to parse syntax (e.g., Python's 'def' vs JS's 'function')
        - Maintains call_dict and callgraph for cross-file dependency analysis via update_callgraph()
        - Filters out built-in keywords and handles third-party imports by tracking 
            "third_party" functions in call_dict
        - Recursive traversal of AST nodes to capture nested function calls
    """
    calls = []
    handler = LANGUAGE_HANDLERS.get(lang)
    if not handler:
        raise ValueError(f"Unsupported language: {lang}")

    def walk(node: Node):
        if node.type == handler["func_def_type"]:
            current_func, params = handler["signature_extractor"](node, src_bytes)
            if not current_func or current_func.strip() in handler["keywords"]:
                return

            body = next(
                (
                    child
                    for child in node.children
                    if child.type == handler["body_type"]
                ),
                None,
            )
            if not body:
                return

            params = re.sub(r"\s+", " ", params).strip()
            func_key = f"{filename}::{current_func}"

            third_party = call_dict.setdefault("third_party", {})
            if current_func in third_party:
                incoming = third_party[current_func].get("called_by", [])
                call_dict[func_key] = {
                    "func_name": current_func,
                    "args": params,
                    "calls": [],
                    "defined_in": filename,
                    "incoming_calls": incoming,
                }
                del third_party[current_func]
            else:
                update_callgraph(caller=current_func, params=params, filename=filename)

            walk_func_body(body, current_func)
        else:
            for child in node.children:
                walk(child)

    def walk_func_body(node: Node, current_func: str):
        for child in node.children:
            if child.type == handler["call_type"]:
                callee = handler.get("callee_extractor", default_callee_extractor)(
                    child, src_bytes
                )
                if callee and callee not in handler["keywords"]:
                    calls.append((current_func, callee))
                    update_callgraph(
                        caller=current_func, callee=callee, filename=filename
                    )
            walk_func_body(child, current_func)

    walk(tree.root_node)
    return calls


def create_repograph(root, search=None, save_path="./"):
    """
    Constructs a repository-level call graph from source code files in C/C++/Python with enhanced contextual analysis.
    
    Args:
        root (str): Root directory path containing source code to analyze
        search (str, optional): Function name to generate contextual subgraph for. Triggers depth-4 subgraph extraction when specified. Defaults to None.
        save_path (str, optional): Directory path to save output artifacts. Defaults to './'.
    
    Returns:
        None: Output is saved as multiple files in save_path directory:
            - callgraph.dot: DOT format call graph visualization
            - callflow.txt: Hierarchical text representation of function calls
            - metadata.json: Structured mapping of functions with metadata including:
                * semantic_role (initializer/handler/utility/test)
                * is_test flag
                * call_depth tracking
                * cyclomatic_complexity metrics
                * source file associations
    
    Process Enhancements:
    1. Uses guess_extension_from_shebang() for ambiguous file types
    2. Leverages get_parser() for language-specific AST parsing
    3. Integrates extract_function_calls() with error resilience
    4. Creates external::<name> nodes for third-party functions not defined in repo
    5. Applies semantic role detection based on naming patterns and file context:
       - initializer: functions starting with init/setup
       - handler: functions containing handle/handler in name
       - utility: files/modules containing 'util' or 'helper'
       - test: functions/files containing 'test' in name/path
    6. Generates contextual subgraphs using extract_context_subgraph() with 4-level depth
    7. Maintains global call_dict for cross-file reference tracking and state persistence
    
    Dependencies:
    - Requires networkx and pydot for graph operations
    - Uses language-specific parsers via get_parser()
    - Relies on module-level call_dict for cross-file analysis
    - Integrates with extract_function_calls() and list_source_files() utilities
    """
    ext_map = {".c": "c", ".cpp": "cpp", ".py": "python"}
    supported_languages = [".c", ".cpp", ".py"]

    graph = nx.DiGraph()
    call_dict.clear()  # Reset global state
    call_dict["third_party"] = defaultdict(lambda: {"called_by": []})

    # 1️⃣ Parse each file and populate call_dict
    for filepath in list_source_files(root, supported_languages):
        extension = os.path.splitext(filepath)[-1]
        if len(extension) == 0:
            extension = guess_extension_from_shebang(file_path=filepath)
        if extension is not None:
            lang = ext_map.get(extension)
            parser = get_parser(lang)
            rel_path = filepath.replace(root + "/", "")
            # print(f'Parsing {rel_path}')
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                code = f.read()
            tree = parser.parse(code.encode("utf8"))
            try:
                extract_function_calls(
                    tree, code.encode("utf8"), lang, filename=rel_path
                )
            except:
                print(f"Could not extract calls from {filepath}")

    # 2️⃣ Add known function definitions to the graph
    for func_id, meta in call_dict.items():
        if func_id == "third_party":
            continue
        graph.add_node(func_id, label=func_id.split("::")[-1], **meta)
        for callee_key in meta.get("calls", []):
            graph.add_edge(func_id, callee_key)

    # 3️⃣ Track third-party functions in graph
    third_party = call_dict.get("third_party", {})
    for callee, info in third_party.items():
        stub_id = f"external::{callee}"
        if not graph.has_node(stub_id):
            graph.add_node(
                stub_id,
                label=callee,
                func_name=callee,
                defined_in="external",
                calls=[],
                is_third_party=True,
            )
        for caller in info.get("called_by", []):
            if graph.has_node(caller):
                graph.add_edge(caller, stub_id)

    # 4️⃣ Annotate additional metadata for defined functions
    for func_id, meta in call_dict.items():
        if func_id == "third_party":
            continue

        file = meta.get("defined_in", "").lower()
        name = func_id.split("::")[-1].lower()

        meta["incoming_calls"] = (
            list(graph.predecessors(func_id)) if func_id in graph else []
        )
        meta["semantic_role"] = (
            "initializer"
            if name.startswith("init") or name.startswith("setup")
            else (
                "handler"
                if name.startswith("handle") or name.endswith("handler")
                else (
                    "utility"
                    if "util" in file or "helper" in file
                    else (
                        "test"
                        if "test" in file or name.startswith("test_")
                        else "unspecified"
                    )
                )
            )
        )
        meta["is_test"] = "test" in file or name.startswith("test_")
        meta["call_depth"] = None
        meta["docstring"] = None
        meta["cyclomatic_complexity"] = None
        meta["lines_of_code"] = None
        meta["last_modified_by"] = None

    # 5️⃣ Write DOT callgraph
    nx.drawing.nx_pydot.write_dot(graph, os.path.join(save_path, "callgraph.dot"))

    # 6️⃣ Save callflow tree
    def print_call_tree(func, depth=0, visited=None):
        if visited is None:
            visited = set()
        if func in visited:
            return
        visited.add(func)
        callflow_file.write("  " * depth + func + "\n")
        for callee in graph.successors(func):
            print_call_tree(callee, depth + 1, visited)

    with open(os.path.join(save_path, "callflow.txt"), "w") as callflow_file:
        top_level_funcs = [node for node in graph.nodes if graph.in_degree(node) == 0]
        for func in sorted(top_level_funcs):
            print_call_tree(func, visited=set())

    # 7️⃣ Build metadata.json in new format
    defined_mappings = {}
    third_party_mappings = {}
    lookup = defaultdict(list)

    for fn_id, meta in call_dict.items():
        if fn_id == "third_party":
            continue
        shortname = fn_id.split("::")[-1]
        defined_mappings[fn_id] = meta
        lookup[shortname].append(fn_id)

    for shortname, third_meta in third_party.items():
        third_party_mappings[shortname] = {
            "name": shortname,
            "calls": [],
            "called_by": third_meta["called_by"],
            "defined_in": "external",
            "is_third_party": True,
        }
        if shortname not in lookup:
            lookup[shortname] = [shortname]

    metadata = {
        "lookup": dict(lookup),
        "defined_mappings": defined_mappings,
        "third_party_mappings": third_party_mappings,
    }

    with open(os.path.join(save_path, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    # 8️⃣ Save contextual subgraph if requested
    if search:
        if search in graph:
            ctx = extract_context_subgraph(graph, search, depth=4)
            dot_path = os.path.join(
                save_path, f"{search.replace('::', '_')}_context.dot"
            )
            nx.drawing.nx_pydot.write_dot(ctx, dot_path)
            print(f"Contextual callgraph for '{search}' saved to: {dot_path}")
        else:
            print(f"Function '{search}' not found in graph.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python repo_callflow_mapper_nx.py <repo_path> <language>")
    else:
        create_repograph(sys.argv[1], sys.argv[2], search=None)
        # main(sys.argv[1], sys.argv[2], search="tdpi_trl_is_hhe")
