import os
import networkx as nx
from typing import Optional

from milo.agents.baseagent import Agent, LLM_ENDPOINT
from milo.agents.tools import (
    build_tool, 
    ViewArchitectureArgs, 
    InspectModuleArgs, 
    InspectCallFlowArgs, 
    FetchSourceArgs, 
    ListDirectoryArgs, 
    TreeDirectoryArgs
)
from milo.codesift.repobrowser import fetch_source_snippet, load_repo_graph, resolve_function_name
from milo.comprehend.browser import list_directory, tree_directory

def get_repocomprehension_agent(repo_path: str, metadata_path: str, endpoint: str = LLM_ENDPOINT) -> Agent:
    
    if not os.path.exists(metadata_path):
        raise FileNotFoundError(f"Semantic map not found at {metadata_path}. Please run SemanticIndexer first.")
        
    G, metadata = load_repo_graph(metadata_path)

    def view_architecture() -> str:
        arch_summaries = metadata.get("architecture_summaries", {})
        if not arch_summaries:
            return "No architecture summaries available."
        
        res = ["=== System Architecture & Entry Points ==="]
        for ep, data in arch_summaries.items():
            res.append(f"\nEntry Point: {ep}")
            res.append(f"Summary: {data.get('summary', 'N/A')}")
        return "\n".join(res)

    def inspect_module(module_name: str) -> str:
        file_mappings = metadata.get("file_mappings", {})
        if module_name not in file_mappings:
            return f"Module '{module_name}' not found in semantic map."
        
        mod_data = file_mappings[module_name]
        res = [f"=== Module: {module_name} ==="]
        res.append(f"Module Summary: {mod_data.get('summary', 'N/A')}\n")
        res.append("Functions defined in this module:")
        
        defined = metadata.get("defined_mappings", {})
        found_funcs = False
        for fn_id, fn_meta in defined.items():
            if fn_meta.get("defined_in") == module_name:
                found_funcs = True
                summary = fn_meta.get("summary", "No summary available.")
                res.append(f"- {fn_id}: {summary}")
                
        if not found_funcs:
            res.append("(No functions indexed for this module)")
            
        return "\n".join(res)

    def inspect_call_flow(entry_function: str) -> str:
        if entry_function not in G.nodes:
            resolved = resolve_function_name(entry_function, metadata)
            if not resolved or resolved not in G.nodes:
                return f"Function '{entry_function}' not found in call graph."
            entry_function = resolved

        edges = list(nx.bfs_edges(G, entry_function))
        nodes_in_order = [entry_function] + [v for u, v in edges]
        
        seen = set()
        ordered_nodes = []
        for n in nodes_in_order:
            if n not in seen:
                seen.add(n)
                ordered_nodes.append(n)
                
        res = [f"=== Call Flow Trace from {entry_function} ==="]
        defined = metadata.get("defined_mappings", {})
        for node in ordered_nodes:
            if node in defined:
                summary = defined[node].get("summary", "No summary available.")
                res.append(f"- {node}: {summary}")
                
        if len(res) == 1:
            res.append("(No downstream functions found)")
            
        return "\n".join(res)

    def read_function_code(fn_name: str, file_path: Optional[str] = None) -> str:
        return fetch_source_snippet(fn_name, G, metadata, repo_path=repo_path, file_hint=file_path)

    def ls_dir(target_path: str = ".") -> str:
        return list_directory(repo_path, target_path)

    def tree_dir(target_path: str = ".", depth: int = 2) -> str:
        return tree_directory(repo_path, target_path, depth)
        
    tools = [
        build_tool("view_architecture", "Returns high-level system summaries and lists of entry points. Use this to understand the big picture first.", ViewArchitectureArgs, view_architecture),
        build_tool("inspect_module", "Returns the summary for a specific file, plus a list of its functions and their 1-sentence summaries.", InspectModuleArgs, inspect_module),
        build_tool("inspect_call_flow", "Returns a list of function summaries that are called (directly or indirectly) originating from a specific entry point.", InspectCallFlowArgs, inspect_call_flow),
        build_tool("read_function_code", "Returns the raw source code of a function. Use this when you need exact implementation details.", FetchSourceArgs, read_function_code),
        build_tool("list_directory", "Lists the contents of a directory in the repo.", ListDirectoryArgs, ls_dir),
        build_tool("tree_directory", "Shows a tree view of a directory.", TreeDirectoryArgs, tree_dir),
    ]

    system_prompt = (
        "You are the RepoComprehensionAgent, an expert software navigator.\n"
        "You have access to a pre-computed multi-layered 'Semantic Map' of this repository.\n"
        "When answering user queries about the codebase, follow this 'Zoom-In' strategy:\n"
        "1. ZOOM OUT: Start by calling `view_architecture` to understand the system entry points and high-level flows.\n"
        "2. MEDIUM ZOOM: Call `inspect_module` on relevant files discovered in step 1 to see their overarching responsibilities and contained functions.\n"
        "3. TRACE: Call `inspect_call_flow` on specific entry points to see the semantic function trace.\n"
        "4. ZOOM IN: ONLY when you need exact implementation details (e.g., to write code or find bugs), call `read_function_code`.\n"
        "Always synthesize your findings into a clear, concise answer for the user."
    )

    return Agent(
        name="RepoComprehensionAgent",
        tools=tools,
        system_prompt=system_prompt,
        model=os.environ.get("GENERIC_MODEL", "miloagent"),
        endpoint=endpoint
    )
