import tree_sitter

from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry


class TreesitterCsharp(Treesitter):
    def __init__(self):
        """
        Initializes a new instance of the class with specific language and token types.

        This constructor initializes an object by calling the parent class's constructor with predefined
        parameters. It sets up the language to C#, and specifies the token types for method declaration,
        identifier, and comment.

        Args:
            self: The instance of the class being initialized.
        """
        super().__init__(
            Language.C_SHARP, "method_declaration", "identifier", "comment"
        )

    def _query_method_name(self, node: tree_sitter.Node):
        """
        Returns the method name from a given AST node.

        This method parses the AST node to extract the method name. If the node
        represents a method declaration and has multiple children of type
        `method_name_identifier`, it returns the second occurrence as the method
        name. Otherwise, it returns the first occurrence.

        Args:
            node (tree_sitter.Node): The AST node to query for the method name.

        Returns:
            Optional[str]: The extracted method name if found, otherwise None.
        """
        first_match = None
        if node.type == self.method_declaration_identifier:
            for child in node.children:
                # if the return type is an object type, then the method name
                # is the second match
                if child.type == self.method_name_identifier and not first_match:
                    first_match = child.text.decode()
                elif child.type == self.method_name_identifier and first_match:
                    return child.text.decode()
        return first_match

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
TreesitterRegistry.register_treesitter(Language.C_SHARP, TreesitterCsharp)
