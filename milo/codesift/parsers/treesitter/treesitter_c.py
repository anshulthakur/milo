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
        """
        Iterates over the major recognizable blocks of the source tree.
        This implementation uses a query to find all supported block types
        and then filters them to return only the outermost, top-level blocks
        in the order they appear in the source code.

        preproc_if is deliberately omitted because it makes the parsing of the
        rest of the header files difficult (guard preproc)
        """
        if not self.tree:
            return

        query_string = """
        [
          (function_definition)
          (declaration)
          (preproc_def)
          (preproc_function_def)
          (preproc_include)
          (type_definition)
          (struct_specifier)
        ] @block
        """
        
        query = tree_sitter.Query(self.language, query_string)
        cursor = tree_sitter.QueryCursor(query)
        captures_dict = cursor.captures(self.tree.root_node)

        if not captures_dict:
            return

        captured_nodes = captures_dict.get('block', [])
        
        # Filter out nodes that are children of other captured nodes
        root_blocks = []
        # Use a set for faster lookups
        captured_nodes_set = set(captured_nodes)

        for node in captured_nodes:
            is_nested = False
            parent = node.parent
            while parent:
                if parent in captured_nodes_set:
                    is_nested = True
                    break
                parent = parent.parent
            if not is_nested:
                root_blocks.append(node)
                
        # Sort the blocks by their starting position in the file
        root_blocks.sort(key=lambda n: n.start_byte)
        
        for block in root_blocks:
            yield block

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
