from enum import Enum

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
