from pydantic import BaseModel
from typing import List, Dict

class RepoIntelModel(BaseModel):
    stack: str
    framework: str
    entry_points: List[str]

class QueryResultModel(BaseModel):
    content: str
    file: str
    start_line: int
    end_line: int
    repo_type: str

class Document:
    def __init__(self, page_content: str, metadata: Dict):
        self.page_content = page_content
        self.metadata = metadata

class CodeSectionModel:
    def __init__(self, content: str, file: str, type: str, start_line: int, end_line: int):
        self.content = content
        self.page_content = content  # For compatibility with embeddings
        self.file = file
        self.type = type
        self.start_line = start_line
        self.end_line = end_line