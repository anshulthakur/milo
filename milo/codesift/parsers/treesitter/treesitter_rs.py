import tree_sitter

from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry


class TreesitterRust(Treesitter):
    def __init__(self):
        """
        Initialize the object with RUST language specific attributes.

        This constructor initializes the object by calling the superclass constructor with parameters
        specific to the RUST programming language. The parameters include the language enum,
        the function item string, the identifier string, and the line comment string.
        """
        super().__init__(Language.RUST, "function_item", "identifier", "line_comment")

    def _query_all_methods(self, node: tree_sitter.Node):
        """
        Queries all method declaration nodes in the AST and collects their associated doc comments.

        This method traverses the abstract syntax tree (AST) recursively to find all method declarations.
        For each method declaration node, it looks for preceding doc comment nodes and combines them into a single string.
        The collected information is stored as dictionaries with 'method' and 'doc_comment' keys in a list.
        """
        methods = []
        if node.type == self.method_declaration_identifier:
            doc_comment_nodes = []
            if (
                node.prev_named_sibling
                and node.prev_named_sibling.type == self.doc_comment_identifier
            ):
                current_doc_comment_node = node.prev_named_sibling
                while (
                    current_doc_comment_node
                    and current_doc_comment_node.type == self.doc_comment_identifier
                ):
                    doc_comment_nodes.append(current_doc_comment_node.text.decode())
                    if current_doc_comment_node.prev_named_sibling:
                        current_doc_comment_node = (
                            current_doc_comment_node.prev_named_sibling
                        )
                    else:
                        current_doc_comment_node = None

            doc_comment_str = ""
            doc_comment_nodes.reverse()
            for doc_comment_node in doc_comment_nodes:
                doc_comment_str += doc_comment_node + "\n"
            if doc_comment_str.strip() != "":
                methods.append({"method": node, "doc_comment": doc_comment_str.strip()})
            else:
                methods.append({"method": node, "doc_comment": None})
        else:
            for child in node.children:
                methods.extend(self._query_all_methods(child))
        return methods


# Register the TreesitterJava class in the registry
TreesitterRegistry.register_treesitter(Language.RUST, TreesitterRust)
