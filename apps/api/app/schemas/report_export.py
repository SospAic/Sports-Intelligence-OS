"""Request/response contracts for one-click intelligence report export."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReportExportItem(BaseModel):
    """One merged search result, already normalised by the caller."""

    title: str = ""
    url: str = ""
    engine: str = ""
    platform: str = ""
    account: str = ""
    #: Pre-formatted publish date; the report never re-parses it.
    published_at: str = ""
    score: float | None = None
    snippet: str = ""
    badges: list[str] = Field(default_factory=list)


class ReportExportRequest(BaseModel):
    query: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=200)
    mode: str = Field(default="", max_length=64)
    summary: str = Field(default="", max_length=4000)
    items: list[ReportExportItem] = Field(default_factory=list, max_length=500)


class ReportExportResponse(BaseModel):
    filename: str
    markdown: str
    #: Standalone printable document used by the browser's print-to-PDF.
    html_document: str
    generated_at: datetime
    total: int
