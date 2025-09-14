from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter, ParsedNode
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry
import tree_sitter

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
        

    def iterate_blocks(self):
        """Iterates over the major recognizable blocks of the source tree."""
        if not self.tree:
            return

        # As per design.md, these are the major blocks. We only consider
        # top-level nodes here.
        supported_types = {
            "function_definition",
            "declaration",
            "preproc_def",
            "preproc_function_def",
            "preproc_include",
            "type_definition",
        }

        for node in self.tree.root_node.children:
            if node.type in supported_types:
                yield node

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
