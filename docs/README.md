# milo Documentation

This directory contains documentation for the milo code analysis platform. The documentation covers the architecture, key components, and usage patterns of the system.

## Table of Contents

- [Architecture Overview](architecture.md)
- [Agents](agents.md)
- [Code Review](codereview.md)
- [CodeSift](codesift.md)
```

```markdown docs/architecture.md
# milo Architecture Overview

The milo platform is designed to provide deep code analysis capabilities by integrating static code analysis with Git change tracking. The system consists of three main components:

1. **Agents**: Responsible for orchestrating workflows and interacting with tools.
2. **Code Review**: Handles Git change analysis and defect detection.
3. **CodeSift**: Provides the underlying code parsing and graph analysis capabilities.

## Data Flow

1. A Git change (e.g., a PR) is processed by the Code Review module.
2. CodeSift parses the affected files to build ASTs and call graphs.
3. Agents coordinate the analysis and generate insights.

## Component Interactions

- **Agents** use tools from **CodeSift** to parse code and **Code Review** to analyze changes.
- **CodeSift** provides parsed ASTs and call graphs to **Code Review**.
- **Code Review** maps changes to functions and identifies potential defects.
```

```markdown docs/agents.md
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
```

```markdown docs/codereview.md
# Code Review

The `milo.codereview` module handles Git change analysis and defect detection. It maps changes to functions and identifies potential issues.

## Key Components

- **`CodeReview`**: The main class for analyzing Git changes.
- **`DefectEnum`**: Enumerates possible defect types.
- **`InputCode`**: Represents the code input for review.

## Workflow

1. **Analyze Git Changes**: Use `review_git_changes` to get the list of changed files.
2. **Map Changes to Functions**: Use `map_hunk_to_function` to link hunks to functions.
3. **Detect Defects**: Run the review to identify potential defects.

## Example Usage

```python
from milo.codereview import CodeReview

# Initialize code review
review = CodeReview()

# Review changes in a repository
review.review_path("path/to/repo", ["file1.py"])
```