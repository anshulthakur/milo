# milo Repository Architecture

## Overview
milo is a code intelligence platform that analyzes code changes and builds dependency graphs for intelligent code reviews.

## Core Components

### Agents
- **Purpose**: Orchestrate code analysis workflows
- **Key Classes**:
  - `BaseAgent`: Foundation for all agents
  - `CodeReviewAgent`: Handles code review tasks

### Code Review Library
- **Purpose**: Analyze Git changes and detect defects
- **Key Functions**:
  - `review_git_changes()`: Maps changed hunks to functions
  - `map_hunk_to_function()`: Links Git hunks to code functions

### CodeSift Library
- **Purpose**: Parse and analyze code using AST
- **Sub-modules**:
  - **Parsers**: Language-specific AST parsers (Python, C, Java, etc.)
  - **Repograph**: Build function call graphs
  - **Repobrowser**: Visualize and navigate code structure

## Workflow
1. Code is parsed into ASTs using Treesitter
2. Call graphs are constructed via `repograph`
3. Git changes are analyzed via `codereview`
4. Agents orchestrate the analysis and generate reviews