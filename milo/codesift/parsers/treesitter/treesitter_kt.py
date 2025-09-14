from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry


class TreesitterKotlin(Treesitter):
    def __init__(self):
        """
        Initializes the class with specific language and token types.

        This method initializes the parent class with predefined parameters:
            - Language.KOTLIN: Specifies that the language is Kotlin.
            - 'function_declaration': Token type for function declarations.
            - 'simple_identifier': Token type for simple identifiers.
            - 'comment': Token type for comments.

        The method uses super() to call the constructor of the parent class with these parameters.
        """
        super().__init__(
            Language.KOTLIN, "function_declaration", "simple_identifier", "comment"
        )


# Register the TreesitterJava class in the registry
TreesitterRegistry.register_treesitter(Language.KOTLIN, TreesitterKotlin)
