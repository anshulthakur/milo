import os
from milo.agents.baseagent import Agent
from milo.agents.tools import (
    build_tool,
    FetchSourceArgs,
    LookaroundSourceArgs,
    GetMetadataArgs,
    GetNeighborsArgs,
    GrepContext,
)

from milo.codesift.repograph_helpers import load_repo_graph
from milo.codesift.repograph_helpers import get_function_metadata
from milo.codesift.repograph_helpers import fetch_source_snippet, get_contextual_neighbors, lookaround_source_snippet
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
    
    The agent follows a structured review workflow defined in the SYSTEM_PROMPT, returning JSON arrays
    of issues with type, file path, line number, description, and suggested fixes. Outputs strictly adhere
    to the specified schema without additional commentary.
    """
    global code_review_agent
    if not code_review_agent:
        G, metadata = load_repo_graph(json_path=metadata_path)
        tools = [
            build_tool(
                "fetch_source_snippet",
                "Fetch the source code implementation of a function from the repo.",
                LookaroundSourceArgs,
                lambda fn_name: fetch_source_snippet(
                    fn_id=fn_name, G=G, metadata=metadata, repo_path=repo_path
                ),
            ),
            build_tool(
                "get_function_metadata",
                "Retrieve structured metadata (like callers, callees, arguments, and file path) for a function.",
                GetMetadataArgs,
                lambda fn_name: get_function_metadata(
                    G=G,
                    fn_id=fn_name,
                    metadata=metadata,
                ),
            ),
            build_tool(
                "get_contextual_neighbors",
                "Find functions that are callers or callees within a given depth from a function.",
                GetNeighborsArgs,
                lambda fn_name, depth=2: get_contextual_neighbors(
                    G=G,
                    fn_id=fn_name,
                    depth=depth,
                    metadata=metadata,
                ),
            ),
            build_tool(
                "lookaround_source_snippet",
                "Fetch the source code around a function definition.",
                FetchSourceArgs,
                lambda fn_name, context_lines=5: lookaround_source_snippet(
                    fn_id=fn_name,
                    G=G,
                    metadata=metadata,
                    context_lines=context_lines,
                    repo_path=repo_path,
                ),
            ),
            build_tool(
                "grep_keyword",
                "Fetches various instances where keyword is used across the codebase in a grep-like manner",
                GrepContext,
                lambda query, filename=None: grep_ast(
                    query=query, file_hint=filename, repo_path=repo_path
                ),
            ),
        ]
        SYSTEM_PROMPT = """You are an expert code reviewer.
Your task is to analyze diffs in source code and return **structured JSON feedback**.
Each diff line is prefixed with its actual line number in the source file (for `-` lines) or in the updated file (for `+` lines). 
Use this line number when reporting issues. Additionally, you may suggest refactoring or relevance based improvements in the entire code (not just the diff).

You are allowed to use tools to gather:
- Source code for the changed function
- Metadata (role, callees, file path)
- Neighboring functions in the call graph

Your final output MUST be a **JSON array** of issues using this format:

[
  {
    "type": "bug" | "performance" | "style" | "best_practice",
    "file": "<filepath>",
    "line": <line number of issue in the new version>,
    "description": "<what is wrong>",
    "suggestion": "<what to do instead>"
  },
  ...
]

Guidelines:
- Only reference added lines (+) in the diff.
- If there are no issues, return `[]`.
- Return valid JSON only — no extra commentary.
"""
        code_review_agent = Agent(
            name="CodeReviewOrchestrator",
            tools=tools,
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
