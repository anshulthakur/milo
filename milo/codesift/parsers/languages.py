import os
from enum import Enum
import traceback

class Language(Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    CPP = "cpp"
    C = "c"
    HTML = "html"
    CSS = "css"
    PHP = "php"
    RUBY = "ruby"
    GO = "go"
    RUST = "rust"
    SWIFT = "swift"
    KOTLIN = "kotlin"
    C_SHARP = "c_sharp"
    OBJECTIVE_C = "objective_c"
    SCALA = "scala"
    PERL = "perl"
    LUA = "lua"
    R = "r"
    HASKELL = "haskell"
    UNKNOWN = "unknown"

def supported_languages():
    """
    Get a list of currently supported languages for parsing and analysis. 
    
    The names of languages are returned as a list of strings.
    """
    return [ lang.value for lang in [Language.PYTHON, Language.C,]]

def supported_extensions():
    """
    Get a list of currently supported file extensions for parsing and analysis.
    """
    return [".py", ".c", ".h"]


def get_programming_language(file_extension: str) -> Language:
    """
    Maps a file extension to its corresponding programming language enum.

    Args:
        file_extension (str): File extension string including leading dot (e.g., '.py')

    Returns:
        Language: Corresponding Language enum value from the Language enum. Returns
        Language.UNKNOWN for unrecognized extensions.

    Notes:
        - Supports modern JS variants (.js, .jsx, .mjs, .cjs) and TypeScript files (.ts, .tsx)
        - Includes compiled languages (.java, .c, .cpp), functional languages (.kt, .hs),
            and systems programming languages (.rs, .go)
        - Used by code analysis tools for syntax highlighting, parsing rules, and
            language-specific feature detection in IDE integrations
        - Case-sensitive matching required (extensions must be lowercase)

    Examples:
        >>> get_programming_language('.tsx')
        <Language.TYPESCRIPT: 2>
        >>> get_programming_language('.kt')
        <Language.KOTLIN: 8>
        >>> get_programming_language('.md')
        <Language.UNKNOWN: 0>
    """
    language_mapping = {
        ".py": Language.PYTHON,
        ".js": Language.JAVASCRIPT,
        ".jsx": Language.JAVASCRIPT,
        ".mjs": Language.JAVASCRIPT,
        ".cjs": Language.JAVASCRIPT,
        ".ts": Language.TYPESCRIPT,
        ".tsx": Language.TYPESCRIPT,
        ".java": Language.JAVA,
        ".kt": Language.KOTLIN,
        ".rs": Language.RUST,
        ".go": Language.GO,
        ".cpp": Language.CPP,
        ".c": Language.C,
        ".h": Language.C,
        ".cs": Language.C_SHARP,
        ".hs": Language.HASKELL,
    }
    return language_mapping.get(file_extension, Language.UNKNOWN)


def get_file_extension(file_name: str) -> str:
    """
    Return the file extension of a given filename using os.path.splitext.

    Args:
        file_name (str): The name of the file, including its extension. Filenames with 
            leading/trailing whitespace are processed as-is (whitespace is not trimmed).

    Returns:
        str: The file extension, including the leading dot (e.g., '.txt') if present. 
            Returns an empty string for filenames without explicit extensions or 
            when only a single dot exists at the end (e.g., 'file.' returns '.').

    Examples:
        >>> get_file_extension('document.pdf')
        '.pdf'
        >>> get_file_extension('README')
        ''
        >>> get_file_extension('.bashrc')
        '.bashrc'
        >>> get_file_extension('data.version1.csv')
        '.csv'
        >>> get_file_extension('single_dot.')
        '.'
    """
    return os.path.splitext(file_name)[-1]


def guess_extension_from_shebang(file_path=None, file_content=None) -> str:
    """
    Analyzes the shebang line of a script to infer its programming language extension.
    
    Args:
        file_path (str, optional): Path to the file. Mutually exclusive with file_content.
        file_content (str, optional): Contents of the file. Mutually exclusive with file_path.
    
    Returns:
        str or None: Mapped file extension (e.g., ".py" for Python) if shebang matches a known pattern,
                        otherwise None. Returns None also on I/O errors or invalid input.
    
    Raises:
        None: Exceptions are caught internally and logged via traceback.print_exc().
    
    Shebang interpreter mapping includes:
        "python" -> ".py"
        "perl" -> ".pl"
        "ruby" -> ".rb"
        "node" -> ".js"
        "java" -> ".java"
    
    Behavior:
    - Extracts the interpreter from the shebang line by taking the last path segment.
    - Performs case-insensitive substring matching of interpreter names against known patterns.
    - Returns first matching extension; otherwise returns None.
    - Handles edge cases like empty file_content or invalid file paths gracefully.
    """
    try:
        if file_path is not None:
            with open(file_path, "r") as file:
                first_line = file.readline().strip()
        else:
            first_line = file_content.splitlines()[0].strip()

        print(first_line)
        if not first_line.startswith("#!"):
            return ''

        # Map common shebang patterns to programming languages
        shebang_map = {
            "python": ".py",
            "perl": ".pl",
            "ruby": ".rb",
            "node": ".js",
            "java": ".java",
        }

        # Extract the interpreter from the shebang
        interpreter = first_line.split("/")[-1]

        # print(interpreter)

        for key, extension in shebang_map.items():
            if key in interpreter.lower():
                return extension

        return ''

    except Exception as e:
        traceback.print_exc()
        return ''

def is_file_supported(file_name: str) -> bool:
    """
    Checks if a file is supported for parsing based on its extension or shebang.

    Args:
        file_name (str): The path to the file to check.

    Returns:
        bool: True if the file is supported, False otherwise.
    """
    extension = get_file_extension(file_name)

    if not extension:
        # If no extension, try to guess from shebang if the file exists
        if os.path.exists(file_name) and not os.path.isdir(file_name):
            extension = guess_extension_from_shebang(file_path=file_name)
        else:
            return False  # No extension and not a file we can read

    if not extension:
        return False

    language = get_programming_language(extension)
    if language == Language.UNKNOWN:
        return False

    return language.value in supported_languages()
