import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.workers.functions import scan_and_alert_high_roi_jobs
from app.api.routes.webhooks import process_whatsapp_tailor

client = TestClient(app)


@pytest.mark.asyncio
async def test_scan_and_alert_high_roi_jobs_worker_task():
    fake_jobs = [
        {
            "id": "job-roi-1",
            "title": "Senior Frontend Engineer",
            "company": "Razorpay",
            "is_high_roi": True,
        }
    ]
    fake_profiles = [
        {
            "id": "user-prof-1",
            "phone": "+919876543210",
            "target_role": "Frontend",
            "user_id": "usr-1",
        }
    ]

    mock_supabase = MagicMock()
    # Mocking jobs select
    mock_jobs_query = MagicMock()
    mock_jobs_query.select.return_value = mock_jobs_query
    mock_jobs_query.eq.return_value = mock_jobs_query
    mock_jobs_query.in_.return_value = mock_jobs_query
    mock_jobs_query.order.return_value = mock_jobs_query
    mock_jobs_query.limit.return_value = mock_jobs_query
    mock_jobs_query.execute.return_value = MagicMock(data=fake_jobs)

    # Mocking profiles select
    mock_profiles_query = MagicMock()
    mock_not = MagicMock()
    mock_not.is_.return_value = mock_profiles_query
    mock_profiles_query.not_ = mock_not
    mock_profiles_query.select.return_value = mock_profiles_query
    mock_profiles_query.execute.return_value = MagicMock(data=fake_profiles)

    def table_router(table_name):
        if table_name == "jobs":
            return mock_jobs_query
        return mock_profiles_query

    mock_supabase.table.side_effect = table_router

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # Not sent yet

    with patch("app.db.supabase.get_service_client", return_value=mock_supabase), \
         patch("app.workers.settings.get_redis_pool", return_value=mock_redis), \
         patch("app.utils.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_send:

        mock_send.return_value = True

        result = await scan_and_alert_high_roi_jobs({}, job_ids=["job-roi-1"])
        assert result["status"] == "ok"
        assert result["alerts_sent"] == 1
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == "+919876543210"
        assert "Razorpay" in args[1]
        assert "Reply 'TAILOR'" in args[1]


def test_whatsapp_webhook_tailor_reply():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = b"usr-1:job-roi-1"

    with patch("app.workers.settings.get_redis_pool", return_value=mock_redis), \
         patch("app.api.routes.webhooks.process_whatsapp_tailor", new_callable=AsyncMock) as mock_tailor_task:

        payload = {
            "From": "whatsapp:+919876543210",
            "Body": "TAILOR",
        }
        res = client.post(
            "/webhooks/whatsapp",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert res.status_code == 200
        assert "<Response></Response>" in res.text
