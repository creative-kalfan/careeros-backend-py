"""Standard CareerOS API response contract.

SUCCESS:
{
  "success": true,
  "data": [...],
  "meta": { "page": 1, "pageSize": 20, "total": 100, "totalPages": 5, "hasNext": true, "hasPrevious": false }
}

ERROR:
{
  "success": false,
  "error": { "code": "...", "message": "..." }
}
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Meta(BaseModel):
    """Pagination metadata for list responses."""

    page: int
    pageSize: int
    total: int
    totalPages: int
    hasNext: bool
    hasPrevious: bool


class ErrorDetail(BaseModel):
    """Error payload for non-2xx responses."""

    code: str
    message: str


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success envelope."""

    success: bool = True
    data: T
    meta: Optional[Meta] = None


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    success: bool = False
    error: ErrorDetail


def build_meta(page: int, page_size: int, total: int) -> Meta:
    """Compute pagination metadata from page/page_size/total."""
    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
    return Meta(
        page=page,
        pageSize=page_size,
        total=total,
        totalPages=total_pages,
        hasNext=page < total_pages,
        hasPrevious=page > 1,
    )