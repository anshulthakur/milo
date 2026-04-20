
from milo.codesift.repobrowser import load_repo_graph
from milo.codesift.repobrowser import get_function_metadata
from milo.codesift.repobrowser import fetch_source_snippet, get_contextual_neighbors, lookaround_source_snippet
from milo.codesift.grepast import grep_ast

from milo.agents.baseagent import Agent
from milo.agents.tools import (
    build_tool,
    FetchSourceArgs,
    LookaroundSourceArgs,
    GetMetadataArgs,
    GetNeighborsArgs,
    GrepContext,
    DelegateTaskArgs,
)

comb_agent = None

def get_agent(metadata_path=None, repo_path=None, repo_name=None):
    global comb_agent
    if not comb_agent:
        G, metadata = load_repo_graph(json_path=metadata_path)
        
        def get_subagent_tools():
            return [
                build_tool(
                    "fetch_source_snippet",
                    "Fetch the source code implementation of a function from the repo.",
                    FetchSourceArgs,
                    lambda fn_name, file_path=None: fetch_source_snippet(fn_id=fn_name, G=G, metadata=metadata, repo_path=repo_path, file_hint=file_path),
                ),
                build_tool(
                    "get_function_metadata",
                    "Retrieve structured metadata (like callers, callees, arguments, and file path) for a function.",
                    GetMetadataArgs,
                    lambda fn_name, file_path=None: get_function_metadata(G=G, fn_id=fn_name, metadata=metadata, file_hint=file_path),
                ),
                build_tool(
                    "get_contextual_neighbors",
                    "Find functions that are callers or callees within a given depth from a function.",
                    GetNeighborsArgs,
                    lambda fn_name, depth=2, file_path=None: get_contextual_neighbors(G=G, fn_id=fn_name, depth=depth, metadata=metadata, file_hint=file_path),
                ),
                build_tool(
                    "lookaround_source_snippet",
                    "Fetch the source code around a function definition from the repo graph.",
                    LookaroundSourceArgs,
                    lambda fn_name, context_lines=30, file_path=None: lookaround_source_snippet(fn_id=fn_name, G=G, metadata=metadata, context_lines=context_lines, repo_path=repo_path, file_hint=file_path),
                ),
                build_tool(
                    "grep_keyword",
                    "Fetches various instances where keyword is used across the codebase in a grep-like manner",
                    GrepContext,
                    lambda query, file_path=None, page=1, ast_context=False: grep_ast(query=query, file_hint=file_path, repo_path=repo_path, page=page, ast_context=ast_context),
                ),
            ]
            
        def delegate_task(task: str, context: str) -> str:
            subagent = Agent(
                name="ResearchSubAgent",
                tools=get_subagent_tools(),
                model="comb",
                max_steps=10,
                system_prompt=(
                    "You are a dedicated code research sub-agent. "
                    "Your job is to answer a specific question about the codebase using the provided tools.\n"
                    "CRITICAL: DO NOT try to solve the user's overarching problem. ONLY answer the specific 'task' requested.\n"
                    "Be extremely concise, factual, and include the relevant code snippets or file paths in your final answer."
                )
            )
            prompt = f"Context: {context}\n\nTask: {task}\n\nPlease find the answer using your tools and return a concise summary of your findings including relevant code."
            return subagent.call(prompt)
            
        tools = [
            build_tool(
                "fetch_source_snippet",
                "Fetch the source code implementation of a function from the repo.",
                FetchSourceArgs,
                lambda fn_name, file_path=None: fetch_source_snippet(fn_id=fn_name, G=G, metadata=metadata, repo_path=repo_path, file_hint=file_path),
            ),
            build_tool(
                "get_function_metadata",
                "Retrieve structured metadata (like callers, callees, arguments, and file path) for a function.",
                GetMetadataArgs,
                lambda fn_name, file_path=None: get_function_metadata(G=G, fn_id=fn_name, metadata=metadata, file_hint=file_path),
            ),
            build_tool(
                "get_contextual_neighbors",
                "Find functions that are callers or callees within a given depth from a function.",
                GetNeighborsArgs,
                lambda fn_name, depth=2, file_path=None: get_contextual_neighbors(G=G, fn_id=fn_name, depth=depth, metadata=metadata, file_hint=file_path),
            ),
            build_tool(
                "delegate_research_task",
                "Delegates a specific, isolated research question to a sub-agent. Use this to find definitions, usages, or trace variables without bloating your own context window.",
                DelegateTaskArgs,
                delegate_task
            )
        ]
        
        comb_agent = Agent(
            name="DocumentationAgent",
            tools=tools,
            model="comb",
            options={
                "num_predict": 4096,
                "temperature": 0.6,
                "top_p": 0.95,
                "repeat_last_n": 64,
                "repeat_penalty": 1.05,
                "seed": 0,
                "top_k": 20,
                "min_p": 0.0,
            },
        )
    return comb_agent
