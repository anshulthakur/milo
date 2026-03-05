from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter, ParsedNode
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry
import tree_sitter
from typing import List, Optional

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
        self.DISPATCHER_REGISTRY = {
            "pthread_create": 2,  # 3rd argument (0-indexed)
            "signal": 1,          # 2nd argument
        }

    def _extract_node_name(self, node) -> Optional[str]:
        declarator = node.child_by_field_name("declarator")
        while declarator:
            if declarator.type == "identifier":
                return declarator.text.decode("utf-8")
            
            # Handle pointer_declarator, function_declarator, etc.
            next_decl = declarator.child_by_field_name("declarator")
            if next_decl:
                declarator = next_decl
            else:
                break
        return None

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
            yield ParsedNode(
                node_type=block.type,
                name=self._extract_node_name(block),  # Add name extraction logic if needed
                doc_comment=self.get_docstring(block),
                source_code=block.text.decode(),
                node=block,
            )

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
                    name_and_params_declarator = declarator
                    if declarator.type == 'pointer_declarator':
                        name_and_params_declarator = declarator.child_by_field_name('declarator')

                    if name_and_params_declarator:
                        name_node = name_and_params_declarator.child_by_field_name('declarator')
                        parameters_node = name_and_params_declarator.child_by_field_name('parameters')
                    else:
                        name_node = None
                        parameters_node = None

                    name = name_node.text.decode() if name_node else None
                    parameters = parameters_node.text.decode() if parameters_node else None
                    
                    if not name and declarator.type == 'type_identifier':
                        name = declarator.text.decode()

                else:
                    name_node = node.child_by_field_name('name')
                    name = name_node.text.decode() if name_node else None
                    parameters = None

                doc_comment = self.get_docstring(node)

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

    def get_docstring(self, node: tree_sitter.Node) -> "str | None":
        # Logic to find an adjacent preceding comment block.
        # This will be adapted from parse_headers_c.py
        if node.prev_named_sibling and node.prev_named_sibling.type == "comment":
            return node.prev_named_sibling.text.decode()
        return None

    def get_dynamic_entry_points(self, scope_node: tree_sitter.Node) -> list[ParsedNode]:
        local_symbols_query_str = """
        [
          (parameter_declaration
            declarator: [ (identifier) @id (pointer_declarator declarator: (identifier) @id) ]
          )
          (declaration
            (init_declarator
              declarator: [ (identifier) @id (pointer_declarator declarator: (identifier) @id) ]
            )
          )
          (declaration
            declarator: [ (identifier) @id (pointer_declarator declarator: (identifier) @id) ]
          )
        ]
        """
        results = []
        local_symbols = set()
        local_symbols_query = tree_sitter.Query(self.language, local_symbols_query_str)
        cursor = tree_sitter.QueryCursor(local_symbols_query)
        capture_results = cursor.captures(scope_node)
        if "id" not in capture_results:
            return results
        for node in capture_results["id"]:
            local_symbols.add(node.text.decode())

        query_string = """
        [
          (call_expression
            arguments: (argument_list
              [
                (identifier) @callback_arg
                (pointer_expression argument: (identifier) @callback_arg)
              ]
            )
          )
          (initializer_list
            [
              (identifier) @callback_arg
              (pointer_expression argument: (identifier) @callback_arg)
            ]
          )
          (assignment_expression
            right: [
              (identifier) @callback_arg
              (pointer_expression argument: (identifier) @callback_arg)
            ]
          )
        ]
        """
        if not self.tree:
            return []

        query = tree_sitter.Query(self.language, query_string)
        cursor = tree_sitter.QueryCursor(query)
        captures = cursor.captures(scope_node)

        
        captured = captures.get('callback_arg')
        if captured:
            for node in captured:
                callback_name = node.text.decode()
                if callback_name not in local_symbols:
                    results.append(
                        ParsedNode(
                            node_type="dynamic_entry_point_candidate",
                            name=callback_name,
                            doc_comment=None,
                            source_code=node.text.decode(),
                            node=node,
                        )
                    )
        return results

# Register the class
TreesitterRegistry.register_treesitter(Language.C, TreesitterC)
