"""Unit tests for NotificationRepository and RecommendationRepository query construction.

Verifies postgrest builder compatibility with supabase-py 2.x (desc=True vs ascending=False).
"""

from unittest.mock import AsyncMock, MagicMock
import pytest
from app.repositories.notification_repository import NotificationRepository
from app.repositories.recommendation_repository import RecommendationRepository


@pytest.mark.asyncio
async def test_notification_repository_list_order_desc():
    repo = NotificationRepository()
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_order = MagicMock()
    mock_limit = MagicMock()
    mock_execute = AsyncMock()

    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq
    mock_eq.order.return_value = mock_order
    mock_order.limit.return_value = mock_limit
    mock_limit.execute = mock_execute

    mock_execute.return_value = MagicMock(data=[{"id": "notif-1"}])

    results = await repo.list_notifications(mock_supabase, user_id="user-123")

    assert results == [{"id": "notif-1"}]
    mock_eq.order.assert_called_once_with("created_at", desc=True)


@pytest.mark.asyncio
async def test_recommendation_repository_list_order_desc():
    repo = RecommendationRepository()
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_order = MagicMock()
    mock_limit = MagicMock()
    mock_execute = AsyncMock()

    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq
    mock_eq.order.return_value = mock_order
    mock_order.limit.return_value = mock_limit
    mock_limit.execute = mock_execute

    mock_execute.return_value = MagicMock(data=[{"id": "rec-1"}])

    # Test sort == "newest"
    results = await repo.list_persisted(mock_supabase, user_id="user-123", sort="newest")
    assert results == [{"id": "rec-1"}]
    mock_eq.order.assert_called_with("created_at", desc=True)

    # Test default sort (match_score)
    mock_eq.order.reset_mock()
    results = await repo.list_persisted(mock_supabase, user_id="user-123", sort="score")
    mock_eq.order.assert_called_with("match_score", desc=True)
