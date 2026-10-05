import os

# Strictly mock external API keys and URLs before module imports and Pydantic settings load.
os.environ["GROQ_API_KEY"] = "test-groq-api-key"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-supabase-service-role"
os.environ["NEXT_PUBLIC_SUPABASE_URL"] = "https://test.supabase.co"
os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"] = "test-supabase-anon"

import pytest

@pytest.fixture(autouse=True)
def mock_external_apis():
    pass

