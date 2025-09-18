# CodeSift

The `milo.codesift` module is the core code analysis engine that provides parsing, graph construction, and context extraction capabilities for multiple programming languages.

## Overview

CodeSift is designed to:
- Parse source code into structured ASTs using Treesitter
- Build call graphs and dependency maps
- Extract contextual information around functions and code patterns
- Support multiple programming languages through language-specific parsers

## Key Components

### Parsers
The parsers submodule contains language-specific parsers that use Treesitter to analyze code. Each parser implements:

| Method | Purpose |
|--------|---------|
| `__init__` | Initializes the parser for a specific language |
| `parse` | Processes a file's source code |
| `get_calls` | Finds function calls in the AST |
| `get_definitions` | Identifies function definitions |
| `get_docstring` | Extracts docstrings |
| `get_imports` | Lists imported modules |

**Supported Languages**:
- Python (via `TreesitterPython`)
- C/C++ (via `TreesitterC`, `TreesitterCpp`)
- Java (via `TreesitterJava`)
- JavaScript (via `TreesitterJavascript`)
- TypeScript (via `TreesitterTypescript`)
- Go (via `TreesitterGo`)
- Haskell (via `TreesitterHaskell`)
- Kotlin (via `TreesitterKotlin`)

### Repograph
The `repograph` module builds and analyzes call graphs of the codebase. It:

- Creates a call graph representation (`Repograph`)
- Maps function calls to their callers and callees
- Extracts context around functions (e.g., nearby code)
- Generates visual representations of code dependencies

Key functionality includes:
- `create_repograph`: Builds the initial code graph
- `extract_function_calls`: Identifies all function calls in the codebase
- `extract_context_subgraph`: Creates focused subgraphs around specific functions
- `print_call_tree`: Visualizes call relationships recursively

### Repobrowser
The `repobrowser` module provides a way to navigate and visualize the codebase. It:
- Allows browsing code files
- Shows function contexts
- Displays call relationships
- Helps in understanding code structure

## Workflow

CodeSift processes code in the following steps:

1. **File Identification**: Identify source files (via `list_source_files`)
2. **AST Parsing**: Parse each file with the appropriate language parser
3. **Context Extraction**: Extract function calls, definitions, imports, and docstrings
4. **Graph Construction**: Build call graphs and dependency maps
5. **Contextual Analysis**: Identify function neighbors and contextual relationships

## Example Usage

```python
from milo.codesift import Repograph

# Create a call graph for a codebase
graph = Repograph("path/to/repo")

# Extract function calls
graph.extract_function_calls()

# Get all functions in the graph
print(graph.get_functions())

# Analyze call relationships
print(graph.get_callers("function_name"))
```

## Supported File Types

CodeSift supports the following file types:
- `.py` (Python)
- `.c` (C)
- `.h` (Header files)
- `.cpp` (C++)
- `.java`
- `.js` (JavaScript)
- `.ts` (TypeScript)
- `.go` (Go)
- `.hs` (Haskell)
- `.kt` (Kotlin)

## Language-Specific Features

Each language parser includes language-specific features:
- **Python**: Support for generators, async functions, decorators
- **C/C++**: Support for structs, typedefs, header files
- **Java**: Support for classes, interfaces, annotations
- **JavaScript/TypeScript**: Support for ES6+ features, type annotations

## Next Steps

- Extend support for new programming languages
- Improve visualization capabilities
- Add more contextual analysis features
- Integrate with CI/CD pipelines for automated code analysis