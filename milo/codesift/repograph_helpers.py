import argparse
import json
import os
import re
import networkx as nx
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.utils import get_file_extension, get_programming_language, guess_extension_from_shebang
from milo.codesift.parsers import supported_languages
from tree_sitter import Node, Tree


def resolve_function_name(
    name: str, metadata: dict, file_hint: str = None
) -> str | None:
    """
    Resolve a short function name to its fully-qualified name (file::func) using metadata.
    
    Args:
        name (str): The short function name to resolve.
        metadata (dict): Metadata dictionary containing a "lookup" key mapping names 
            to lists of qualified function names (e.g., {"func": ["module.py::func"]}).
        file_hint (str, optional): If provided, restricts matches to the specified file.
    
    Returns:
        str | None: The fully-qualified name if unambiguous and found; otherwise None. 
            Returns None if no matches, multiple matches without file_hint, or no match in file_hint.
    
    Behavior:
        1. If file_hint is provided, filters matches to those starting with "file_hint::".
        2. If exactly one match remains after filtering, returns it.
        3. If no matches or ambiguity (multiple matches without file_hint), returns None.
    
    Repository Context:
        Used by code analysis tools to disambiguate function references across files. 
        Typically called when resolving cross-file dependencies in the call graph.
        Integrates with metadata generated during static analysis of the codebase.
    """
    lookup = metadata.get("lookup", {})
    matches = lookup.get(name, [])

    if not matches:
        return None

    if file_hint:
        for m in matches:
            if m.startswith(file_hint + "::"):
                return m
        return None  # Not found in specified file

    if len(matches) == 1:
        return matches[0]

    return None  # Ambiguous without file hint


def load_repo_graph(json_path="metadata.json"):
    """
    Load repository metadata into a NetworkX DiGraph representing function call relationships.

    Args:
        json_path (str): Path to JSON metadata file containing 'lookup', 'defined_mappings',
                            and 'third_party_mappings' sections. Defaults to 'metadata.json'.

    Returns:
        Tuple[nx.DiGraph, dict]: A directed graph where nodes represent functions with attributes,
                                    and edges represent call dependencies. The second element is the raw metadata.

    The function constructs a graph model of the codebase by:
    1. Parsing defined functions from 'defined_mappings' with split-qualified labels (last segment after "::")
    2. Adding third-party functions as unlabeled nodes (using raw function names without prefixes)
    3. Creating edges between callers and callees, automatically adding missing third-party nodes
        with inferred labels if they don't exist
    4. Storing reverse lookup table in graph.metadata['lookup'] for node ID resolution

    Special handling ensures:
    - Third-party functions (without module prefixes) are properly connected
    - Dangling edges to undefined functions are preserved for analysis
    - Node attributes from metadata are retained (e.g., file paths, line numbers)

    Example usage context:
    - Used by 'analyze_call_chains()' to visualize dependencies
    - Provides input for 'generate_dependency_report()' in code_quality module
    """
    with open(json_path, "r") as f:
        metadata_all = json.load(f)

    print(f"Loaded metadata from {json_path}")
    lookup = metadata_all.get("lookup", {})
    defined = metadata_all.get("defined_mappings", {})
    third_party = metadata_all.get("third_party_mappings", {})

    def get_label(fn_id):
        return fn_id.split("::")[-1]

    G = nx.DiGraph()
    for fn_id, meta in defined.items():
        G.add_node(fn_id, label=get_label(fn_id), **meta)

    for fn_id, meta in third_party.items():
        G.add_node(fn_id, label=fn_id, **meta)  # no prefix for third-party

    for fn_id, meta in defined.items():
        for callee in meta.get("calls", []):
            if not G.has_node(callee):
                # allow dangling third-party edges
                G.add_node(callee, label=get_label(callee))
            G.add_edge(fn_id, callee)

    G.graph["lookup"] = lookup
    return G, metadata_all


def get_function_metadata(
    G, fn_id: str, metadata: dict = None, file_hint: str = None
) -> dict | None:
    """
    Retrieves structured metadata for a function identified by `fn_id` from either a graph (G) or fallback metadata mappings.

    Args:
        G: NetworkX graph containing preloaded function metadata in node attributes.
        fn_id (str): Function identifier, may be short (unqualified name) or fully qualified ("module::name").
        metadata (dict, optional): Dictionary containing "lookup" and "defined_mappings" for resolution fallbacks.
        file_hint (str, optional): File path context to disambiguate function resolution when multiple functions share the same name.

    Returns:
        dict: Function metadata if found in graph or fallback mappings, None if not found/ambiguous.

    Notes:
        1. Resolves short identifiers via `resolve_function_name()` using metadata[file_hint] to disambiguate between similarly named functions across files.
        2. Fallbacks to metadata["defined_mappings"] if graph lookup fails (useful for unloaded functions or partial graph populations).
        3. Ambiguous/missing identifiers trigger diagnostic messages and return None; callers should handle missing results gracefully.
        4. Prioritizes graph-based resolution (G.nodes) over fallback mappings to ensure metadata consistency with the latest graph state.
    """
    print("get_function_metadata")

    resolved_id = fn_id

    if "::" not in fn_id:
        if not metadata:
            print("[Missing metadata for lookup resolution]")
            return None
        resolved_id = resolve_function_name(fn_id, metadata, file_hint=file_hint)

    if not resolved_id:
        print(f"[Function not found or ambiguous: {fn_id}]")
        return None

    if resolved_id in G.nodes:
        return G.nodes[resolved_id]

    # fallback (if not loaded into graph, but present in metadata)
    meta_lookup = metadata.get("defined_mappings", {})
    return meta_lookup.get(resolved_id)


def get_contextual_neighbors(G, fn_id, metadata=None, depth=2, file_hint=None):
    """
    Retrieve all function nodes within ±depth hops from a given function in the call graph.

    This function performs bidirectional traversal (both callers and callees) up to the specified depth
    in a directed graph representation of function relationships. Handles partial/short function names
    by resolving them against metadata, with optional file context for disambiguation.

    Args:
        G (networkx.DiGraph): Directed call graph containing function nodes and edges
        fn_id (str): Target function identifier (fully qualified or short name)
        metadata (dict, optional): Repository metadata for name resolution
        depth (int, optional): Maximum traversal depth in both directions (default: 2)
        file_hint (str, optional): File path to prioritize during name resolution

    Returns:
        list: Function IDs of all contextually related nodes within the specified depth range,
                excluding the original function itself. Returns empty list if no neighbors found.

    Notes:
        - Ambiguous or unresolved function names will trigger a warning and return None
        - Resolution prefers fully qualified names (containing '::')
        - Traversal includes both direct and indirect relationships at each depth level
    """
    resolved_id = fn_id

    if "::" not in fn_id:  # short name
        resolved_id = resolve_function_name(fn_id, metadata, file_hint=file_hint)

    if not resolved_id:
        print("[Function not found or ambiguous]")
        return

    if resolved_id not in G:
        return []

    visited = {resolved_id}
    frontier = {resolved_id}

    for _ in range(depth):
        next_frontier = set()
        for node in frontier:
            next_frontier.update(set(G.successors(node)))
            next_frontier.update(set(G.predecessors(node)))
        next_frontier -= visited
        visited.update(next_frontier)
        frontier = next_frontier

    visited.remove(resolved_id)
    return list(visited)


def search_functions_by_pattern(G, pattern):
    """
    Perform regex-based search on function IDs (node identifiers) and their corresponding labels in a call graph.

    Args:
        G (networkx.Graph): A function call graph where nodes represent functions. Node attributes may include 'label' 
                            (typically the function name). Node IDs often follow a module-qualified format like 'module::function'.
        pattern (str): Regular expression pattern to match against node IDs and labels.

    Returns:
        list: A list of node IDs (strings) where the regex matches either the node ID or its associated label.

    Behavior:
        - Compiles the input pattern into a regex.
        - For each node in G, checks if the regex matches the node ID or the 'label' attribute.
        - If no 'label' exists for a node, extracts the last segment of the node ID (split by '::') as fallback.
    """
    regex = re.compile(pattern)
    matches = []
    for node in G.nodes:
        label = G.nodes[node].get("label", node.split("::")[-1])
        if regex.search(node) or regex.search(label):
            matches.append(node)
    return matches


def summarize_module_hierarchy(G):
    """
    Groups functions by their defining module/file within a call graph.

    Args:
        G (networkx.Graph): A function call graph where nodes represent functions. Each node must have a 'defined_in' attribute 
                            indicating the file/module path where the function is defined (e.g., 'src/mymodule.py').

    Returns:
        dict: Keys are module/file paths (str), values are lists of function IDs (node identifiers) defined in that module.
                Functions without a 'defined_in' attribute are grouped under '<unknown>'.

    Notes:
        - This utility is used by the main() function in repograph_helpers to analyze module-level organization.
        - Function IDs correspond to node identifiers in the graph (typically formatted as 'module::function').
    """
    from collections import defaultdict

    module_map = defaultdict(list)
    for node in G.nodes:
        file = G.nodes[node].get("defined_in", "<unknown>")
        module_map[file].append(node)
    return dict(module_map)


def lookaround_source_snippet(
    fn_id, G, metadata=None, context_lines=0, repo_path="", file_hint=None
):
    """
    Fetches source code snippet containing the definition of a specified function,
    including surrounding context lines. Resolves ambiguous function names using metadata
    and repository path information.
    
    Args:
        fn_id (str): Function identifier (fully qualified name or short name)
        G (networkx.Graph): Repository graph containing function metadata
        metadata (dict, optional): Precomputed function metadata cache
        context_lines (int): Number of lines to include before/after function definition
        repo_path (str): Base path for repository files
        file_hint (str): Optional file path hint for name resolution
    
    Returns:
        str: Source code snippet or error message if function not found/file inaccessible
    
    Handles cases where:
    - Function name is ambiguous (requires metadata resolution)
    - Defined file path is missing or invalid
    - Function definition cannot be located in source
    """
    resolved_id = fn_id

    if "::" not in fn_id:  # short name
        resolved_id = resolve_function_name(fn_id, metadata, file_hint=file_hint)

    if not resolved_id:
        print("[Function not found or ambiguous]")
        return

    meta = G.nodes.get(resolved_id)
    if not meta:
        return "[Function not found]"

    filepath = meta.get("defined_in")
    if len(repo_path) > 0:
        filepath = os.path.join(repo_path, filepath)

    if not filepath or not os.path.exists(filepath):
        return f"[Source file missing: {filepath}]"

    try:
        func_name = resolved_id.split("::")[-1]
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if re.search(rf"\b{re.escape(func_name)}\b", line):
                start = max(i - context_lines, 0)
                end = min(i + context_lines + 1, len(lines))
                return "".join(lines[start:end])
        return "[Function not located in source]"
    except Exception as e:
        return f"[Error reading source: {str(e)}]"


def fetch_source_snippet(fn_id, G, metadata=None, repo_path="", file_hint=None):
    """
    Fetch the source code implementation of a function from the repository graph.

    Args:
        fn_id (str): Function identifier. Can be short name or fully qualified path.
        G (networkx.Graph): Repository graph containing function metadata nodes.
        metadata (dict, optional): Additional context for resolving ambiguous function names.
        repo_path (str, optional): Root directory of the repository. Defaults to empty string.
        file_hint (str, optional): Filesystem hint to resolve function definitions.

    Returns:
        str: Source code block if found, or error message in [square brackets].

    Process:
    1. Resolves ambiguous function names using metadata/file hints
    2. Maps file extensions to language parsers (C/C++/Python)
    3. Parses AST to extract exact function definition block
    4. Returns raw source text with syntax highlighting markers

    Error Handling:
    - [Function not found/ambiguous] for unresolved identifiers
    - [Source file missing: ...] for missing files
    - [Language not supported] for unsupported extensions
    - [Error reading source: ...] for parsing/IO errors
    """
    resolved_id = fn_id

    if "::" not in fn_id:  # short name
        resolved_id = resolve_function_name(fn_id, metadata, file_hint=file_hint)

    if not resolved_id:
        print("[Function not found or ambiguous]")
        return

    meta = G.nodes.get(resolved_id)
    if not meta:
        return "[Function not found]"

    func_name = resolved_id.split("::")[-1]
    filepath = meta.get("defined_in")
    if len(repo_path) > 0:
        filepath = os.path.join(repo_path, filepath)

    if not filepath or not os.path.exists(filepath):
        return f"[Source file missing: {filepath}]"

    extension = get_file_extension(filepath)
    if len(extension) == 0:
        extension = guess_extension_from_shebang(file_path=filepath)
    if len(extension) == 0:
        print(f"Undetermined extension in {filepath}")
        return
    lang = get_programming_language(extension)
    if lang.value not in supported_languages():
        print(f"Language {lang} not supported yet.")
        return
    
    treesitter = Treesitter.create_treesitter(lang)

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
        treesitter.parse(code.encode("utf8"))
        functions = treesitter.get_definitions("function")
        for func in functions:
            if func.name == func_name:
                return func.source_code
        return "[Function not located in source]"

    except Exception as e:
        return f"[Error reading source: {str(e)}]"


def main():
    """
    CLI entry point for Repository Oracle - provides programmatic access to code repository analysis.
    
    Operations:
      meta: Retrieve structured metadata about a function (callers/callees/args)
      neighbors: Find contextual neighbors in call graph up to specified depth
      search: Find functions matching regex pattern across codebase
      modules: Generate module hierarchy summary
      snippet: Fetch source code implementation with configurable context lines
      body: Fetch source code implementation (exact body)
    
    Args:
      --fn FUNCTION_ID   Target function identifier (file.c::function_name format)
      --pattern PATTERN  Regex pattern for function search
      --depth DEPTH      Neighborhood traversal depth (default: 2)
      --context LINES    Source snippet context lines (default: 5)
      --prefix PATH      Repository root path prefix (default: empty)
    
    Requires JSON repo graph at --json path (default: metadata.json)
    """
    parser = argparse.ArgumentParser(description="Repository Oracle CLI")
    parser.add_argument(
        "command",
        choices=["meta", "neighbors", "search", "modules", "snippet", "body"],
        help="Operation to perform",
    )
    parser.add_argument("--fn", help="Function ID (e.g., file.c::function_name)")
    parser.add_argument("--pattern", help="Regex pattern to search")
    parser.add_argument(
        "--depth", type=int, default=2, help="Depth for neighborhood traversal"
    )
    parser.add_argument("--json", default="metadata.json", help="Path to Oracle JSON")
    parser.add_argument(
        "--context", type=int, default=5, help="Lines of context in snippet"
    )
    parser.add_argument(
        "--prefix", type=str, default="", help="Prefix path to find the repo"
    )
    args = parser.parse_args()

    G, metadata_all = load_repo_graph(args.json)

    if args.command == "meta" and args.fn:
        result = get_function_metadata(G, args.fn, metadata=metadata_all)
        print(json.dumps(result, indent=2) if result else "[Function not found]")

    elif args.command == "neighbors" and args.fn:
        neighbors = get_contextual_neighbors(G, args.fn, metadata=metadata_all, depth=args.depth)
        print(json.dumps(neighbors, indent=2))

    elif args.command == "search" and args.pattern:
        matches = search_functions_by_pattern(G, args.pattern)
        print(json.dumps(matches, indent=2))

    elif args.command == "modules":
        modmap = summarize_module_hierarchy(G)
        print(json.dumps(modmap, indent=2))

    elif args.command == "snippet" and args.fn:
        snippet = lookaround_source_snippet(
            args.fn, G, metadata=metadata_all, context_lines=args.context, repo_path=args.prefix
        )
        print(snippet)
    
    elif args.command == "body" and args.fn:
        snippet = fetch_source_snippet(
            args.fn, G, metadata=metadata_all, repo_path=args.prefix
        )
        print(snippet)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
