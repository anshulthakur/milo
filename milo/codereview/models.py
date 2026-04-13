from enum import Enum
from pydantic import BaseModel, TypeAdapter, Field
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

class VerificationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"

class VerificationResult(BaseModel):
    id: str
    status: VerificationStatus
    reason: str

VerificationListModel = TypeAdapter(list[VerificationResult])


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
    file_path: Optional[str] = None
    request: str = ("Please revise the docstring for the provided method. "
                    "Return the result in JSON format using the schema provided. "
                    "Use tools to fetch further context from the repository graph to ensure documentation relevance. ")

class ToolSummaryInput(BaseModel):
    tool_name: str = Field(..., description="The tool that was called")
    tool_args: str = Field(..., description="The arguments passed to the tool")
    raw_output: str = Field(..., description="The raw, unsummarized output of the tool")

class ToolSummaryOutput(BaseModel):
    extracted_data: str = Field(..., description="The exact, verbatim data segments from the raw_output that are relevant to the thinking. Do not summarize or add commentary.")
