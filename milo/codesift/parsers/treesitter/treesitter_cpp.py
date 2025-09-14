import tree_sitter

from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry


class TreesitterCpp(Treesitter):

    def __init__(self):
        """
        Initializes the object with specific language settings and patterns.

        This constructor sets up the object for C++ language processing by specifying
        the language, function definition pattern, identifier pattern, and comment pattern.
        """
        super().__init__(Language.CPP, "function_definition", "identifier", "comment")

    def _query_method_name(self, node: tree_sitter.Node):
        """
        Extracts the method name from a given AST node.

        This method traverses the AST structure to find the method name identifier within a method declaration node.
        It handles pointer declarator by skipping them when searching for the function declarator that contains the method name.

        Args:
            node (tree_sitter.Node): The AST node representing a method declaration.

        Returns:
            Optional[str]: The decoded text of the method name identifier if found, otherwise None.
        """
        if node.type == self.method_declaration_identifier:
            for child in node.children:
                # if method returns pointer, skip pointer declarator
                if child.type == "pointer_declarator":
                    child = child.children[1]
                if child.type == "function_declarator":
                    for child in child.children:
                        if child.type == self.method_name_identifier:
                            return child.text.decode()
        return None


# Register the TreesitterJava class in the registry
TreesitterRegistry.register_treesitter(Language.CPP, TreesitterCpp)
