# Agents

The `milo.agents` module provides a framework for creating and managing code analysis agents. These agents orchestrate workflows by calling tools and processing responses.

## Key Classes

- **`Agent`**: The base class for all agents.
  - **`__init__`**: Initializes the agent with a name, tools, and configuration.
  - **`call`**: Executes a workflow with optional follow-up instructions.
  - **`_handle_response`**: Processes the response from the model.

## Example Usage

```python
from milo.agents import Agent

# Create an agent with tools for code review
agent = Agent(
    name="CodeReviewer",
    tools=[
        # Tools for code review
    ]
)

# Execute a review workflow
agent.call("Review the PR for file1.py")
```

## Tool Integration

Agents use tools defined in `milo.agents.tools.py` to interact with the system. Each tool is a callable function with a specific schema.

## Custom Tool Creation

To extend the agent capabilities, developers can create custom tools by subclassing the `Tool` class. Each tool must define:

- A unique name
- A descriptive purpose
- A schema for input arguments
- A function that processes the arguments

Example:

```python docs/agents.md
from milo.agents.tools import Tool, GetMetadataArgs

class GetFileMetadata(Tool):
    def __init__(self):
        super().__init__(
            name="get_file_metadata",
            description="Retrieve metadata for a source file",
            schema=GetMetadataArgs,
            func=self._get_file_metadata
        )
    
    def _get_file_metadata(self, args: GetMetadataArgs) -> dict:
        """Fetch file metadata from the filesystem."""
        return {
            "file_path": args.file_path,
            "language": self._detect_language(args.file_path),
            "line_count": self._count_lines(args.file_path)
        }
    
    def _detect_language(self, file_path: str) -> str:
        # Implementation to detect language based on file extension
        # ...
        pass
    
    def _count_lines(self, file_path: str) -> int:
        # Implementation to count lines in a file
        # ...
        pass
```

This example shows how to create a tool that retrieves file metadata, which can be used by agents during code analysis.

## Agent Workflows

Agents execute workflows through the `call` method, which takes a natural language instruction and processes it through the agent's tools. The workflow typically involves:

1. **Parsing the instruction** into actionable steps
2. **Calling tools** to gather necessary information
3. **Combining results** into a coherent response
4. **Handling follow-ups** with additional instructions

Example workflow:

```python docs/agents.md
from milo.agents import Agent
from milo.agents.tools import GetFileMetadata

agent = Agent(
    name="CodeAnalyzer",
    tools=[
        GetFileMetadata()
    ]
)

# Analyze a file's metadata
result = agent.call("Show metadata for file1.py")
print(result)
```

## Error Handling

Agents can handle errors through the `_handle_response` method, which processes the model's response. This method allows for:

- Validating the response
- Handling errors in the tool calls
- Generating user-friendly error messages

## Advanced Features

- **State Management**: Agents can maintain state between calls using the `options` parameter in the `__init__` method.
- **Contextual Awareness**: Agents can use context from previous interactions to improve responses.
- **Multi-Step Workflows**: Complex tasks can be broken into multiple steps with follow-up instructions.


```python docs/agents.md
from milo.agents.tools import Tool, GetMetadataArgs

class GetFileMetadata(Tool):
    def __init__(self):
        super().__init__(
            name="get_file_metadata",
            description="Retrieve metadata for a source file",
            schema=GetMetadataArgs,
            func=self._get_file_metadata
        )
    
    def _get_file_metadata(self, args: GetMetadataArgs) -> dict:
        """Fetch file metadata from the filesystem."""
        return {
            "file_path": args.file_path,
            "language": self._detect_language(args.file_path),
            "line_count": self._count_lines(args.file_path)
        }
    
    def _detect_language(self, file_path: str) -> str:
        # Implementation to detect language based on file extension
        # ...
        pass
    
    def _count_lines(self, file_path: str) -> int:
        # Implementation to count lines in a file
        # ...
        pass
```