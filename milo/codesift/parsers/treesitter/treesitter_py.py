from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter, ParsedNode
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry
import tree_sitter

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

    def iterate_blocks(self):
        """Iterates over the major recognizable blocks of the source tree."""
        if not self.tree:
            return

        supported_types = {
            "function_definition",
            "class_definition",
            "import_statement",
            "import_from_statement",
            "expression_statement",
            "decorated_definition",
            "if_statement",
        }

        for node in self.tree.root_node.children:
            if node.type in supported_types:
                yield node

    def get_definitions(self, node_type: str) -> list[ParsedNode]:
        query_string = self.queries.get(node_type)
        if not query_string or not self.tree:
            return []

        query = tree_sitter.Query(self.language, query_string)
        cursor = tree_sitter.QueryCursor(query)
        captures = cursor.captures(self.tree.root_node)

        results = []
        
        if 'definition' in captures:
            for node in captures['definition']:
                name_node = node.child_by_field_name('name')
                name = name_node.text.decode() if name_node else None

                if name and node.type == 'function_definition':
                    parent = node.parent
                    while parent:
                        if parent.type == 'class_definition':
                            class_name_node = parent.child_by_field_name('name')
                            if class_name_node:
                                class_name = class_name_node.text.decode()
                                name = f"{class_name}.{name}"
                            break
                        parent = parent.parent

                doc_comment = self._get_doc_comment(node)

                parameters_node = node.child_by_field_name("parameters")
                parameters = parameters_node.text.decode() if parameters_node else None

                results.append(
                    ParsedNode(
                        node_type=node_type,
                        name=name,
                        doc_comment=doc_comment,
                        source_code=node.text.decode(),
                        node=node,
                        parameters=parameters,
                    )
                )
        return results

    def get_calls(self, scope_node: tree_sitter.Node) -> list[ParsedNode]:
        query_string = "(call) @call"
        if not self.tree:
            return []

        query = tree_sitter.Query(self.language, query_string)
        cursor = tree_sitter.QueryCursor(query)
        captures = cursor.captures(scope_node)

        results = []
        
        if 'call' in captures:
            for node in captures['call']:
                name_node = node.child_by_field_name("function")
                name = name_node.text.decode() if name_node else None
                if name:
                    results.append(
                        ParsedNode(
                            node_type="call",
                            name=name,
                            doc_comment=None,
                            source_code=node.text.decode(),
                            node=node,
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
