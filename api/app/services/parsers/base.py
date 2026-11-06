from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ParsedPage:
    """Represents a single parsed page of a document."""
    page_no: int  # 1-based index
    markdown: str
    plain_text: str
    char_count: int
    has_table: bool = False
    has_figure: bool = False
    ocr_used: Optional[bool] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class ParsedDocument:
    """Represents the complete parsed result of a document."""
    parser_name: str
    parser_version: str
    page_count: int
    pages: List[ParsedPage]
    raw_json: Optional[Dict[str, Any]] = None
    full_markdown: Optional[str] = None


class DocumentParserError(Exception):
    """Base exception for document parsing failures."""
    pass


class ParserUnavailableError(DocumentParserError):
    """Raised when the parsing service is unreachable or down."""
    pass


class DocumentParser(ABC):
    """Abstract interface for all document parsing engines."""

    @abstractmethod
    async def parse(
        self,
        file_path: Path,
        options: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        """
        Parse a document file on disk into structured pages.

        Args:
            file_path: Absolute path to the document file.
            options: Optional parser-specific tuning parameters (e.g. ocr, page_range).

        Returns:
            ParsedDocument containing per-page markdown and metadata.
        """
        pass

