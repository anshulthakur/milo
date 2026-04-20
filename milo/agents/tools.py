from typing import Callable
from pydantic import BaseModel, Field
from typing import Optional


class BaseToolArgs(BaseModel):
    reasoning: str = Field(..., description="A terse, single-sentence explanation of why you are calling this tool and what you are looking for.")


class Tool:
    def __init__(
        self, name: str, description: str, func: Callable, schema: type[BaseModel]
    ):
        """
        Initialize an agent/function wrapper with validation schema.

        This constructor creates a wrapper class that combines an executable function 
        with Pydantic-based validation for both input parameters and output responses. 
        The schema is used to validate inputs before execution and format outputs after.

        Args:
            name (str): Human-readable identifier for the agent/function
            description (str): Detailed explanation of the function's purpose and behavior
            func (Callable): Function to be wrapped and executed by the agent
            schema (type[BaseModel]): Pydantic model class defining input/output validation rules

        Note:
            - The schema must be a BaseModel subclass (class type) for proper validation
            - Input parameters will be validated against the schema before func execution
            - Output responses will be validated and transformed using the same schema
            - This pattern is commonly used in agent systems interfacing with external APIs/LLMs
        """
        self.name = name
        self.description = description
        self.func = func
        self.schema = schema  # <- a Pydantic model class, not an instance


# ---- Tool Input Schemas ----


class FetchSourceArgs(BaseToolArgs):
    fn_name: str = Field(..., description="The function name to fetch source for")
    file_path: Optional[str] = Field(None, description="The file path where the function is defined")


class LookaroundSourceArgs(BaseToolArgs):
    fn_name: str = Field(..., description="The function name to fetch source for")
    context_lines: Optional[int] = Field(
        5, description="Number of lines of context around the function"
    )
    file_path: Optional[str] = Field(None, description="The file path where the function is defined")


class GetMetadataArgs(BaseToolArgs):
    fn_name: str = Field(..., description="The function name to fetch metadata for")
    file_path: Optional[str] = Field(None, description="The file path where the function is defined")


class GetNeighborsArgs(BaseToolArgs):
    fn_name: str = Field(..., description="The function name to find neighbors for")
    depth: Optional[int] = Field(2, description="Depth to traverse callers and callees")
    file_path: Optional[str] = Field(None, description="The file path where the function is defined")


class GrepContext(BaseToolArgs):
    query: str = Field(..., description="String query to search for in the codebase")
    file_path: Optional[str] = Field(
        None,
        description="Optional file path in which search to be done."
        " If not specified, search done on entire codebase",
    )
    page: Optional[int] = Field(
        1,
        description="Page number of the results to fetch. Default is 1."
    )
    ast_context: Optional[bool] = Field(
        False,
        description="If True, includes AST-aware context around the matches. If False, returns simple line matches. Default is False."
    )


class ListDirectoryArgs(BaseToolArgs):
    target_path: Optional[str] = Field(".", description="The directory path to list, relative to the repository root.")


class TreeDirectoryArgs(BaseToolArgs):
    target_path: Optional[str] = Field(".", description="The directory path to tree, relative to the repository root.")
    depth: Optional[int] = Field(2, description="The maximum depth to traverse.")


class ViewArchitectureArgs(BaseToolArgs):
    pass


class InspectModuleArgs(BaseToolArgs):
    module_name: str = Field(..., description="The file path or module name to inspect (e.g., 'src/main.py')")


class InspectCallFlowArgs(BaseToolArgs):
    entry_function: str = Field(..., description="The fully qualified entry point function name to trace (e.g., 'main.py::main')")


class CreateFileArgs(BaseToolArgs):
    file_path: str = Field(..., description="The path of the new file, relative to the repository root.")
    content: str = Field(..., description="The complete content of the new file.")


class ApplyDiffArgs(BaseToolArgs):
    file_path: str = Field(..., description="The path of the file to patch, relative to the repository root.")
    diff: str = Field(..., description="A standard unified diff patch (including --- and +++ headers) to apply to the file. Ensure you provide enough context lines for the patch to apply cleanly.")

class ReplaceSnippetArgs(BaseToolArgs):
    file_path: str = Field(..., description="The path of the file to modify, relative to the repository root.")
    search_text: str = Field(..., description="The exact text to be replaced. Must match the file's contents perfectly, including indentation and whitespace. Include enough context to make it unique.")
    replace_text: str = Field(..., description="The new text that will replace the search_text.")

class RewindArgs(BaseToolArgs):
    marker: str = Field(..., description="The rewind marker string (e.g., abc123def456) to retrieve original uncompressed content.")


class DelegateTaskArgs(BaseToolArgs):
    task: str = Field(..., description="The precise, isolated question or research task you need the sub-agent to answer (e.g., 'Find where the variable X is defined and its type').")
    context: str = Field(..., description="Brief context on why this is being asked, so the sub-agent understands the perspective without getting distracted by the overall objective.")


# ---- Tool Builder ----
def build_tool(
    name: str, description: str, model: type[BaseModel], func: Callable
) -> Tool:
    """
    Factory function that creates a validated tool wrapper around a callable function with Pydantic schema integration.

    Constructs an executable tool with automatic input validation, serialization, and error handling for agent systems. The returned Tool instance executes the target function only after successfully parsing and validating arguments through the provided Pydantic model.

    Args:
        name (str): Human-readable identifier for the tool used in system metadata
        description (str): Detailed documentation of the tool's purpose, behavior, and constraints
        model (type[BaseModel]): Pydantic model defining input schema (validation rules, serialization format)
        func (Callable): Core implementation to execute after validation succeeds

    Returns:
        Tool: Configured executable with:
            - Input validation via model
            - Schema-aware parameter handling
            - Name/description metadata
            - Error propagation from validation failures

    Integration:
        Typically used to wrap raw functions for agent tool registries that require strict input contracts.
        Validation errors during execution will be propagated as ValueError exceptions.

    Example:
        >>> def add(a: int, b: int) -> int:
        ...     return a + b
        
        >>> class AddArgs(BaseModel):
        ...     a: int
        ...     b: int
        
        >>> tool = build_tool("add", "Performs addition", AddArgs, add)
    """
    def wrapped_func(**kwargs):
        parsed_args = model(**kwargs)
        call_args = parsed_args.model_dump()
        call_args.pop("reasoning", None)
        return func(**call_args)

    return Tool(
        name=name,
        description=description,
        func=wrapped_func,
        schema=model,
    )
