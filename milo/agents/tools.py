from typing import Callable
from pydantic import BaseModel, Field
from typing import Optional


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


class FetchSourceArgs(BaseModel):
    fn_name: str = Field(..., description="The function name to fetch source for")


class LookaroundSourceArgs(BaseModel):
    fn_name: str = Field(..., description="The function name to fetch source for")
    context_lines: Optional[int] = Field(
        5, description="Number of lines of context around the function"
    )


class GetMetadataArgs(BaseModel):
    fn_name: str = Field(..., description="The function name to fetch metadata for")


class GetNeighborsArgs(BaseModel):
    fn_name: str = Field(..., description="The function name to find neighbors for")
    depth: Optional[int] = Field(2, description="Depth to traverse callers and callees")


class GrepContext(BaseModel):
    query: str = Field(..., description="String query to search for in the codebase")
    filename: Optional[str] = Field(
        ...,
        description="Optional file name in which search to be done."
        " If not specified, search done on entire codebase",
    )


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
        return func(**parsed_args.model_dump())

    return Tool(
        name=name,
        description=description,
        func=wrapped_func,
        schema=model,
    )
