from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry


class TreesitterJavascript(Treesitter):
    def __init__(self):
        """
        Initializes a new instance of the class with specific language and pattern parameters.

        This constructor initializes the instance by calling the super class's constructor with predefined
        parameters. The parameters include the language as JAVASCRIPT, and specific patterns for function
        declaration, identifier, and comment.

        Args:
            self: Reference to the current instance of the class.
        """
        super().__init__(
            Language.JAVASCRIPT, "function_declaration", "identifier", "comment"
        )


# Register the TreesitterJava class in the registry
TreesitterRegistry.register_treesitter(Language.JAVASCRIPT, TreesitterJavascript)
