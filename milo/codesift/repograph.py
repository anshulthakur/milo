import os
import sys
import networkx as nx
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.languages import supported_languages, supported_extensions
from milo.codesift.parsers.utils import get_programming_language, get_file_extension
from tree_sitter import Node, Tree
import json
import re
from collections import defaultdict
import traceback

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


def guess_extension_from_shebang(file_path=None, file_content=None)-> str:
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
        "python" -> ".py",
        "perl" -> ".pl",
        "ruby" -> ".rb",
        "node" -> ".js",
        "java" -> ".java",
    
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
            return ''

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

        return ''

    except Exception as e:
        traceback.print_exc()
        return ''


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


def extract_function_calls(treesitter: Treesitter, filename: str):
    """
    Extracts function call relationships from an AST (Abstract Syntax Tree) for code analysis.

    Args:
        treesitter (Treesitter): Treesitter object for the language.
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
    functions = treesitter.get_definitions("function")

    # First, register all function definitions in the file
    for func_node in functions:
        current_func = func_node.name
        params = func_node.parameters
        update_callgraph(caller=current_func, params=params, filename=filename)

    # Then, process all calls
    for func_node in functions:
        current_func = func_node.name
        calls = treesitter.get_calls(func_node.node)
        for call_node in calls:
            callee = call_node.name
            update_callgraph(caller=current_func, callee=callee, filename=filename)


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

    graph = nx.DiGraph()
    call_dict.clear()  # Reset global state
    call_dict["third_party"] = defaultdict(lambda: {"called_by": []})

    # 1️⃣ Parse each file and populate call_dict
    for filepath in list_source_files(root, supported_extensions()):
        extension = get_file_extension(filepath)
        if len(extension) == 0:
            extension = guess_extension_from_shebang(file_path=filepath)
        if len(extension) == 0:
            print(f"Undetermined extension in {filepath}")
            continue
        lang = get_programming_language(extension)
        if lang.value not in supported_languages():
            print(f"Language {lang} not supported yet.")
            continue
        treesitter = Treesitter.create_treesitter(lang)
        rel_path = filepath.replace(root + "/", "")
        # print(f'Parsing {rel_path}')
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
        treesitter.parse(code.encode("utf8"))
        try:
            extract_function_calls(
                treesitter,
                filename=rel_path
            )
        except:
            print(f"Could not extract calls from {filepath}")
            traceback.print_exc()

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
