# Tree-sitter Wrapper Library Design

This document outlines a new, more extensible design for the tree-sitter wrapper library. The current implementation is focused on parsing only methods and functions. The new design will support a wider range of parsing operations and provide a more consistent interface.

## 1. Core Concepts

The refactored library will be built around these core concepts:

- **Generic Parsing Interface:** Instead of a single `parse` method focused on functions, the base `Treesitter` class will provide a more generic interface to query different types of nodes from the Abstract Syntax Tree (AST).
- **Language-Specific Implementations:** Each supported language will have its own concrete implementation of the `Treesitter` ABC. These classes will contain the specific tree-sitter queries for that language.
- **Extensible Node Types:** The library will be able to extract various AST nodes, such as classes, structs, imports, and variables, not just functions.
- **Unified C/C++ Handling:** The logic from `parse_headers_c.py` will be integrated into the `TreesitterC` and `TreesitterCpp` classes to provide a unified way of handling C and C++ source code, including headers.

## 2. Proposed Class Structure

### `milo/codesift/parsers/treesitter/treesitter.py`

This file will contain the base abstract class for all language-specific parsers.

```python
from abc import ABC, abstractmethod
import tree_sitter
from tree_sitter_language_pack import get_language, get_parser

from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry

class ParsedNode:
    """A generic container for a parsed node from the AST."""
    def __init__(
        self,
        node_type: str,
        name: "str | None",
        doc_comment: "str | None",
        source_code: str,
        node: tree_sitter.Node,
    ):
        self.node_type = node_type
        self.name = name
        self.doc_comment = doc_comment
        self.source_code = source_code
        self.node = node

class Treesitter(ABC):
    def __init__(self, language: Language):
        self.parser = get_parser(language.value)
        self.language = get_language(language.value)
        self.tree = None

    @staticmethod
    def create_treesitter(language: Language) -> "Treesitter":
        return TreesitterRegistry.create_treesitter(language)

    def parse(self, file_bytes: bytes):
        """Parses the file content and builds the AST."""
        self.tree = self.parser.parse(file_bytes)

    @abstractmethod
    def get_definitions(self, node_type: str) -> list[ParsedNode]:
        """
        Gets all definitions of a certain type from the parsed tree.
        e.g., 'function', 'class', 'struct'
        """
        pass

    @abstractmethod
    def get_imports(self) -> list[ParsedNode]:
        """Gets all import statements from the parsed tree."""
        pass

    # Other common queries can be added here as abstract methods.
```

### Language-Specific Implementations (e.g., `treesitter_py.py`)

Each language will implement the `Treesitter` ABC.

```python
from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter, ParsedNode
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry

class TreesitterPython(Treesitter):
    def __init__(self):
        super().__init__(Language.PYTHON)
        self.queries = {
            "function": """
                (function_definition
                  name: (identifier) @name) @definition
            """,
            "class": """
                (class_definition
                  name: (identifier) @name) @definition
            """,
            "import": """
                (import_statement) @import
            """
        }

    def get_definitions(self, node_type: str) -> list[ParsedNode]:
        query_string = self.queries.get(node_type)
        if not query_string or not self.tree:
            return []

        query = self.language.query(query_string)
        captures = query.captures(self.tree.root_node)

        results = []
        definition_nodes = {}

        for node, capture_name in captures:
            if capture_name == "definition":
                # Use node id to group captures for the same definition
                if node.id not in definition_nodes:
                    definition_nodes[node.id] = {"definition_node": node}
            if capture_name == "name":
                 # This assumes a name is found for a definition that has already been seen
                if node.parent.id in definition_nodes:
                    definition_nodes[node.parent.id]["name_node"] = node

        for node_id, parts in definition_nodes.items():
            definition_node = parts["definition_node"]
            name_node = parts.get("name_node")
            name = name_node.text.decode() if name_node else None

            # Logic to find doc comment for the definition_node
            doc_comment = self._get_doc_comment(definition_node)

            results.append(
                ParsedNode(
                    node_type=node_type,
                    name=name,
                    doc_comment=doc_comment,
                    source_code=definition_node.text.decode(),
                    node=definition_node,
                )
            )
        return results

    def get_imports(self) -> list[ParsedNode]:
        # Implementation for get_imports
        pass

    def _get_doc_comment(self, node: tree_sitter.Node) -> "str | None":
        # Language-specific logic to extract doc comments
        # For python, it's the first statement in the body if it's a string
        if node.type in ("function_definition", "class_definition"):
            body = node.child_by_field_name("body")
            if body and body.named_child_count > 0:
                first_statement = body.named_children[0]
                if first_statement.type == "expression_statement" and first_statement.named_child_count > 0:
                    child = first_statement.named_children[0]
                    if child.type == "string":
                        return child.text.decode()
        return None

# Register the class
TreesitterRegistry.register_treesitter(Language.PYTHON, TreesitterPython)
```

### `milo/codesift/parsers/treesitter/treesitter_c.py`

The C parser will be updated to handle header-like constructs, integrating the logic from `parse_headers_c.py`.

```python
# (imports...)

class TreesitterC(Treesitter):
    def __init__(self):
        super().__init__(Language.C)
        self.queries = {
            "function": "...",
            "struct": """
                (struct_specifier
                    name: (type_identifier) @name) @definition
            """,
            "typedef": """
                (type_definition
                    declarator: (type_identifier) @name) @definition
            """
        }

    def get_definitions(self, node_type: str) -> list[ParsedNode]:
        # Similar implementation to Python, but using C-specific queries
        # and doc comment logic (usually a comment block before the definition)
        pass

    def get_imports(self) -> list[ParsedNode]:
        # C uses #include, so this would query for preprocessor directives
        pass

    def _get_doc_comment(self, node: tree_sitter.Node) -> "str | None":
        # Logic to find an adjacent preceding comment block.
        # This will be adapted from parse_headers_c.py
        if node.prev_named_sibling and node.prev_named_sibling.type == "comment":
            return node.prev_named_sibling.text.decode()
        return None

# Register the class
TreesitterRegistry.register_treesitter(Language.C, TreesitterC)
```

## 3. Key Changes and Benefits

- **Decoupling:** The core parsing logic is decoupled from the language-specific details.
- **Extensibility:** Adding support for new languages or new types of parsable nodes is much simpler. You just need to add a new query to the `queries` dictionary in the language-specific class, or a new method to the base class and implement it.
- **Consistency:** All parsers will have a consistent API.
- **Maintainability:** The code will be easier to understand, maintain, and test.
- **Integration of `parse_headers_c.py`:** The functionality for parsing C headers will be part of the main library, not a separate script.

## 4. Extractable Node Types

To provide a comprehensive parsing solution, the library will identify and extract various "top-level" or "globally-scoped" blocks of code. The goal is to treat any distinguishable and independent block of code as a parsable unit.

Below are the proposed lists of extractable node types for Python and C. The `node_type` in the `ParsedNode` will correspond to the keys in the `queries` dictionary (e.g., "function", "class", "import_statement").

### Python (`source.python`)

-   **`function_definition`**: Standalone functions.
-   **`class_definition`**: Class definitions, including their methods. Methods inside classes will be extractable as `function_definition` nodes within the class scope.
-   **`import_statement`**: `import foo`
-   **`import_from_statement`**: `from foo import bar`
-   **`expression_statement`**: Top-level expressions and logic. This can include global variable assignments (`foo = "bar"`) and executable blocks like `if __name__ == "__main__":`. We might need to add heuristics to group related expression statements.

### C (`source.c`)

-   **`function_definition`**: A function with its body.
-   **`declaration`**: A declaration, which can be a function prototype, a global variable declaration, or a struct/union/enum declaration. We will need to distinguish between them.
    -   Function declarations (prototypes).
    -   Global variable declarations/initializations.
-   **`preproc_def`**: A preprocessor macro definition (`#define`).
-   **`preproc_function_def`**: A preprocessor function-like macro definition (`#define FOO(x)`).
-   **`preproc_include`**: An include directive (`#include <foo.h>`).
-   **`type_definition`**: A `typedef` statement.
-   **`struct_specifier`**: A `struct` definition.
-   **`union_specifier`**: A `union` definition.
-   **`enum_specifier`**: An `enum` definition.

This list can be expanded in the future to support more node types as needed.

## 5. Migration Plan

1.  **Refactor `Treesitter` base class:** Implement the new ABC structure in `treesitter.py`.
2.  **Create `ParsedNode`:** Add the `ParsedNode` data class.
3.  **Refactor `TreesitterPython`:** Update `treesitter_py.py` to the new design as a reference implementation.
4.  **Refactor other languages:** Gradually refactor the other `treesitter_*` files.
5.  **Integrate C header parsing:** Refactor `treesitter_c.py` and `treesitter_cpp.py`, incorporating the logic from `parse_headers_c.py`.
6.  **Remove `parse_headers_c.py`:** Once its logic is fully integrated, the old file can be removed.
7.  **Update `TreesitterRegistry`:** Ensure the registry works with the new class structure.
8.  **Update client code:** Any code that uses the old `parse` method will need to be updated to use the new `get_definitions` or other `get_*` methods.
