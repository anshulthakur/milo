from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter import Treesitter
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry


class TreesitterJava(Treesitter):
    def __init__(self):
        super().__init__(
            Language.JAVA, "method_declaration", "identifier", "block_comment"
        )


# Register the TreesitterJava class in the registry
TreesitterRegistry.register_treesitter(Language.JAVA, TreesitterJava)
