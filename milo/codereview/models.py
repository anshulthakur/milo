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
