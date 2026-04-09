import json
import time
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field

class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    OBSOLETE = "OBSOLETE"

class ReviewAnchor(BaseModel):
    """
    Anchors a review to a specific location and semantic context in the code.
    """
    file_path: str
    symbol_name: Optional[str] = None
    symbol_type: Optional[str] = None
    patch_fingerprint: str
    ast_fingerprint: Optional[str] = None
    line_range_start: int
    line_range_end: int

class ReviewComment(BaseModel):
    """
    A single message in the review conversation.
    """
    role: str  # "bot" or "user"
    content: str
    timestamp: float = Field(default_factory=time.time)

class ReviewHistoryItem(BaseModel):
    """
    Tracks the verdict of the review across different commits.
    """
    commit_sha: str
    verdict: str  # e.g., "fail", "pass"
    timestamp: float = Field(default_factory=time.time)

class Review(BaseModel):
    """
    Represents a persistent code review thread.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: ReviewStatus = ReviewStatus.OPEN
    anchor: ReviewAnchor
    conversation: List[ReviewComment] = []
    history: List[ReviewHistoryItem] = []

    def add_bot_comment(self, content: str):
        self.conversation.append(ReviewComment(role="bot", content=content))

    def add_user_reply(self, content: str):
        self.conversation.append(ReviewComment(role="user", content=content))

    def mark_resolved(self):
        self.status = ReviewStatus.RESOLVED

    def mark_obsolete(self):
        self.status = ReviewStatus.OBSOLETE

class ReviewStore:
    """
    Persistence layer for reviews. Handles loading/saving to a JSON file.
    """
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.reviews: Dict[str, Review] = {}
        self.load()

    def load(self):
        """Loads reviews from the storage file."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Handle list of reviews
                    if isinstance(data, list):
                        for r_data in data:
                            review = Review(**r_data)
                            self.reviews[review.id] = review
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading review store: {e}")
                self.reviews = {}

    def save(self):
        """Persists current state to the storage file."""
        data = [r.model_dump() for r in self.reviews.values()]
        # Ensure directory exists
        if not self.storage_path.parent.exists():
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add_review(self, review: Review):
        """Adds or updates a review in the store."""
        self.reviews[review.id] = review
        self.save()

    def get_review(self, review_id: str) -> Optional[Review]:
        return self.reviews.get(review_id)

    def get_reviews_by_file(self, file_path: str, status: Optional[ReviewStatus] = None) -> List[Review]:
        """Retrieves reviews for a specific file, optionally filtered by status."""
        results = [r for r in self.reviews.values() if r.anchor.file_path == file_path]
        if status:
            results = [r for r in results if r.status == status]
        return results
    
    def get_open_reviews_for_symbol(self, file_path: str, symbol_name: Optional[str]) -> List[Review]:
        """Retrieves all OPEN reviews for a specific file and symbol."""
        return [
            r for r in self.reviews.values() 
            if r.status == ReviewStatus.OPEN and r.anchor.file_path == file_path and r.anchor.symbol_name == symbol_name
        ]

    def find_matching_review(self, file_path: str, symbol_name: Optional[str]) -> Optional[Review]:
        """
        Finds an existing OPEN review that matches the file and symbol name.
        This is the core logic for 'Phase 1: Robust Diff & Anchoring'.
        """
        for review in self.reviews.values():
            if (review.status == ReviewStatus.OPEN and 
                review.anchor.file_path == file_path and 
                review.anchor.symbol_name == symbol_name):
                return review
        return None
