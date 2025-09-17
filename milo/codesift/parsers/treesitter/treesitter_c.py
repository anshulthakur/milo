from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter, ParsedNode
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry
import tree_sitter

class TreesitterC(Treesitter):
    def __init__(self):
        super().__init__(Language.C)
        self.queries = {
            "function": "(function_definition) @definition",
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
        query_string = self.queries.get(node_type)
        if not query_string or not self.tree:
            return []

        query = tree_sitter.Query(self.language, query_string)
        cursor = tree_sitter.QueryCursor(query)
        captures = cursor.captures(self.tree.root_node)

        results = []
        if "definition" in captures:
            for node in captures["definition"]:
                declarator = node.child_by_field_name('declarator')
                if declarator:
                    name_node = declarator.child_by_field_name('declarator')
                    name = name_node.text.decode() if name_node else None
                    parameters_node = declarator.child_by_field_name('parameters')
                    parameters = parameters_node.text.decode() if parameters_node else None
                else:
                    name = None
                    parameters = None

                doc_comment = self._get_doc_comment(node)

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
        query_string = "(call_expression) @call"
        if not self.tree:
            return []

        query = tree_sitter.Query(self.language, query_string)
        cursor = tree_sitter.QueryCursor(query)
        captures = cursor.captures(scope_node)

        results = []
        if "call" in captures:
            for node in captures["call"]:
                fn_node = node.child_by_field_name("function")
                if fn_node and fn_node.type == "identifier":
                    name = fn_node.text.decode()
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
