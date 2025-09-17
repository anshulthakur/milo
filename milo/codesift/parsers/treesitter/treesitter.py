from abc import ABC, abstractmethod
import tree_sitter
from tree_sitter_language_pack import get_language, get_parser

from milo.codesift.parsers import Language
from milo.codesift.parsers.treesitter.treesitter_registry import TreesitterRegistry

class ParsedNode:
    """A generic container for a parsed node from the AST."""
    def __init__(
        self,
        node_type: str,
        name: "str | None",
        doc_comment: "str | None",
        source_code: str,
        node: tree_sitter.Node,
        parameters: "list[str] | None" = None,
    ):
        self.node_type = node_type
        self.name = name
        self.doc_comment = doc_comment
        self.source_code = source_code
        self.node = node
        self.parameters = parameters

class Treesitter(ABC):
    def __init__(self, language: Language):
        self.parser = get_parser(language.value)
        self.language = get_language(language.value)
        self.tree = None

    @staticmethod
    def create_treesitter(language: Language) -> "Treesitter":
        return TreesitterRegistry.create_treesitter(language)

    def parse(self, file_bytes: bytes):
        """Parses the file content and builds the AST."""
        self.tree = self.parser.parse(file_bytes)

    @abstractmethod
    def iterate_blocks(self):
        """Iterates over the major recognizable blocks of the source tree."""
        pass

    @abstractmethod
    def get_definitions(self, node_type: str) -> list[ParsedNode]:
        """
        Gets all definitions of a certain type from the parsed tree.
        e.g., 'function', 'class', 'struct'
        """
        pass

    @abstractmethod
    def get_imports(self) -> list[ParsedNode]:
        """Gets all import statements from the parsed tree."""
        pass

    @abstractmethod
    def get_calls(self, scope_node: tree_sitter.Node) -> list[ParsedNode]:
        """Gets all call expressions from a given scope."""
        pass

    # Other common queries can be added here as abstract methods.