import os
from milo.agents.baseagent import Agent
from milo.agents.tools import (
    build_tool,
    FetchSourceArgs,
    LookaroundSourceArgs,
    GetMetadataArgs,
    GetNeighborsArgs,
    GrepContext,
    DelegateTaskArgs,
    get_filesystem_tools
)

from milo.codesift.repobrowser import load_repo_graph
from milo.codesift.repobrowser import get_function_metadata
from milo.codesift.repobrowser import fetch_source_snippet, get_contextual_neighbors, lookaround_source_snippet
from milo.codesift.grepast import grep_ast
from pydantic import BaseModel, TypeAdapter
from enum import Enum
from typing import TypeAlias


class DefectEnum(str, Enum):
    style = "style"
    bug = "bug"
    performance = "performance"
    best_practice = "best_practice"


class CodeReview(BaseModel):
    type: DefectEnum
    file: str
    line: int
    description: str
    suggestion: str


ReviewList: TypeAlias = list[CodeReview]
ReviewListModel = TypeAdapter(ReviewList)


code_review_agent = None


def get_agent(metadata_path=None, repo_path=None, repo_name=None):
    """
    Initializes and returns a singleton code review agent with repository analysis capabilities.
    
    The function creates an Agent instance equipped with tools for codebase inspection,
    metadata retrieval, source navigation, and AST-based keyword searches. If already
    initialized, returns the cached agent to avoid redundant setup.
    
    Parameters:
        metadata_path (str): Path to repository metadata JSON file for graph construction
        repo_path (str): Base directory path of the code repository being analyzed
        repo_name (str): Optional identifier for repository context (currently unused but reserved)
    
    Returns:
        Agent: Code review agent with these capabilities:
            - Fetch function source code via `fetch_source_snippet` (default 5 lines context)
            - Retrieve structured metadata via `get_function_metadata`
            - Find call graph neighbors via `get_contextual_neighbors` (depth=2 by default)
            - Get surrounding source code with `lookaround_source_snippet`
            - Perform AST-based grep via `grep_keyword`
    
        Agent is configured with specific generation parameters:
            temperature: 0.6
            top_p: 0.8
            num_predict: 4096
            repeat_penalty: 1.05
    
    The agent follows a structured review workflow defined in its Model file, returning JSON arrays
    of issues with type, file path, line number, description, and suggested fixes. Outputs strictly adhere
    to the specified schema without additional commentary.
    """
    global code_review_agent
    if not code_review_agent:
        G, metadata = load_repo_graph(json_path=metadata_path)
        
        def get_subagent_tools():
            sub_tools = [
                build_tool(
                    "fetch_source_snippet",
                    "Fetch the source code implementation of a function from the repo.",
                    FetchSourceArgs,
                    lambda fn_name, file_path=None: fetch_source_snippet(
                        fn_id=fn_name, G=G, metadata=metadata, repo_path=repo_path, file_hint=file_path
                    ),
                ),
                build_tool(
                    "get_function_metadata",
                    "Retrieve structured metadata (like callers, callees, arguments, and file path) for a function.",
                    GetMetadataArgs,
                    lambda fn_name, file_path=None: get_function_metadata(
                        G=G, fn_id=fn_name, metadata=metadata, file_hint=file_path,
                    ),
                ),
                build_tool(
                    "get_contextual_neighbors",
                    "Find functions that are callers or callees within a given depth from a function.",
                    GetNeighborsArgs,
                    lambda fn_name, depth=2, file_path=None: get_contextual_neighbors(
                        G=G, fn_id=fn_name, depth=depth, metadata=metadata, file_hint=file_path,
                    ),
                ),
                build_tool(
                    "lookaround_source_snippet",
                    "Fetch the source code around a function definition.",
                    FetchSourceArgs,
                    lambda fn_name, context_lines=5, file_path=None: lookaround_source_snippet(
                        fn_id=fn_name, G=G, metadata=metadata, context_lines=context_lines, repo_path=repo_path, file_hint=file_path,
                    ),
                ),
                build_tool(
                    "grep_keyword",
                    "Fetches various instances where keyword is used across the codebase in a grep-like manner",
                    GrepContext,
                    lambda query, file_path=None, page=1, ast_context=False: grep_ast(
                        query=query, file_hint=file_path, repo_path=repo_path, page=page, ast_context=ast_context
                    ),
                ),
            ]
            if repo_path:
                sub_tools.extend(get_filesystem_tools(repo_path))
            return sub_tools
            
        def delegate_task(task: str, context: str) -> str:
            subagent = Agent(
                name="ResearchSubAgent",
                tools=get_subagent_tools(),
                model="crab",
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
                lambda fn_name, file_path=None: fetch_source_snippet(
                    fn_id=fn_name, G=G, metadata=metadata, repo_path=repo_path, file_hint=file_path
                ),
            ),
            build_tool(
                "get_function_metadata",
                "Retrieve structured metadata (like callers, callees, arguments, and file path) for a function.",
                GetMetadataArgs,
                lambda fn_name, file_path=None: get_function_metadata(
                    G=G, fn_id=fn_name, metadata=metadata, file_hint=file_path,
                ),
            ),
            build_tool(
                "get_contextual_neighbors",
                "Find functions that are callers or callees within a given depth from a function.",
                GetNeighborsArgs,
                lambda fn_name, depth=2, file_path=None: get_contextual_neighbors(
                    G=G, fn_id=fn_name, depth=depth, metadata=metadata, file_hint=file_path,
                ),
            ),
            build_tool(
                "delegate_research_task",
                "Delegates a specific, isolated research question to a sub-agent. Use this to find definitions, usages, or trace variables without bloating your own context window.",
                DelegateTaskArgs,
                delegate_task
            )
        ]
        if repo_path:
            tools.extend(get_filesystem_tools(repo_path))
        
        code_review_agent = Agent(
            name="CodeReviewOrchestrator",
            tools=tools,
            model="crab",
            options={
                "num_predict": 4096,
                "temperature": 0.6,
                "top_p": 0.8,
                "repeat_last_n": 64,
                "repeat_penalty": 1.05,
                "seed": 0,
                "top_k": 0,
                "min_p": 0.1,
            },
            # format=ReviewListModel.json_schema(),
        )
    return code_review_agent
