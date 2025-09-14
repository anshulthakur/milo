from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry


class TreesitterGo(Treesitter):
    def __init__(self):
        """
        Initializes the object with specific language and pattern parameters.

        The constructor sets up the object by calling the superclass constructor with predefined
        values for the language, function declaration pattern, identifier pattern, and comment pattern.

        Args:
            self: Reference to the current instance of the class.
        """
        super().__init__(Language.GO, "function_declaration", "identifier", "comment")


# Register the TreesitterJava class in the registry
TreesitterRegistry.register_treesitter(Language.GO, TreesitterGo)
