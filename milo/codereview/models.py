from enum import Enum
from pydantic import BaseModel, TypeAdapter
from typing import List, Optional, TypeAlias

class DefectEnum(str, Enum):
    style = "style"
    bug = "bug"
    performance = "performance"
    best_practice = "best_practice"


class CodeReview(BaseModel):
    type: DefectEnum
    file: str
    line: int
    description: str
    suggestion: str


ReviewList: TypeAlias = list[CodeReview]
ReviewListModel = TypeAdapter(ReviewList)

class ReviewInputCode(BaseModel):
    language: str
    method: str
    file_path: Optional[str] = None
    diff_hunk: Optional[str] = None
    request: str

class InputCode(BaseModel):
    language: str
    method: str
    docstring: str = ""
    request: str = ("Please revise the docstring for the provided method. "
                    "Return the result in JSON format using the schema provided. "
                    "Use tools to fetch further context from the repository graph to ensure documentation relevance. ")
