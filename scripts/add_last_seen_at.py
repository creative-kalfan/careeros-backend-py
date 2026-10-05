import os
import psycopg2
import dotenv

dotenv.load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

project_ref = SUPABASE_URL.split("//")[-1].split(".")[0] if SUPABASE_URL else ""
conn_string = os.environ.get(
    "DATABASE_URL",
    f"postgresql://postgres:{SUPABASE_SERVICE_ROLE_KEY}@db.{project_ref}.supabase.co:5432/postgres",
)

try:
    conn = psycopg2.connect(conn_string)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'jobs' AND column_name = 'last_seen_at'"
    )
    if cursor.fetchone():
        print("Column last_seen_at already exists")
    else:
        cursor.execute("ALTER TABLE public.jobs ADD COLUMN last_seen_at TIMESTAMPTZ NULL;")
        conn.commit()
        print("Added last_seen_at column")

    cursor.close()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
