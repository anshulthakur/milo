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
