"""Diagnostic test for the real Jobs API with actual HTTP requests.

TEMPORARY DIAGNOSTIC (per task instructions):
- All HTTP requests use a 5-second timeout (no unlimited requests).
- Verifies server via GET /health before testing /api/jobs.
- Only tests the unauthenticated /api/jobs endpoint.
- Prints explicit diagnostics: SERVER STARTED, HEALTH REQUEST START,
  HEALTH RESPONSE, JOBS REQUEST START, JOBS RESPONSE.
"""

import requests
import json
import time
import os
import subprocess
import sys
import traceback
from pathlib import Path

HTTP_TIMEOUT = 5  # seconds — every HTTP request must have timeout <= 5s


def wait_for_server(base_url, max_wait=15):
    """Poll /health until the server responds or max_wait is exceeded.

    Each poll uses a short timeout (<= 5s) to avoid hanging.
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.5)
    return False


def test_jobs_api():
    """Test GET /api/jobs (unauthenticated only)."""
    base_url = "http://127.0.0.1:8000"
    jobs_url = f"{base_url}/api/jobs"
    start = time.time()

    try:
        print("Testing GET /api/jobs (unauthenticated)...")
        print("JOBS REQUEST START")
        response = requests.get(
            jobs_url,
            params={"page": 1, "page_size": 10},
            timeout=HTTP_TIMEOUT,
        )
        elapsed = time.time() - start
        print(f"JOBS RESPONSE: status={response.status_code}, elapsed={elapsed:.3f}s")
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        print(f"Body: {response.text[:500]}")

        if response.status_code == 200:
            data = response.json()
            print(f"✅ GET /api/jobs works")
            print(f"   Success: {data.get('success')}")
            print(f"   Jobs returned: {len(data.get('data', []))}")
            print(f"   Total: {data.get('meta', {}).get('total', 0)}")
            return True
        else:
            print(f"❌ GET /api/jobs failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False

    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        print(f"❌ GET /api/jobs TIMED OUT after {elapsed:.3f}s (timeout={HTTP_TIMEOUT}s)")
        print(f"   Error type: requests.exceptions.Timeout")
        traceback.print_exc()
        return False
    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ Jobs API test failed after {elapsed:.3f}s: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        traceback.print_exc()
        return False


def main():
    """Run diagnostic API tests."""
    print("=" * 60)
    print("DIAGNOSTIC: TEST REAL JOB API (unauthenticated only)")
    print("=" * 60)

    # Determine the backend root directory (parent of the test file location)
    backend_root = Path(__file__).resolve().parent
    os.chdir(str(backend_root))
    print(f"Working directory: {os.getcwd()}")
    print(f"Backend root: {backend_root}")
    print(f"Python executable: {sys.executable}")

    # Start the server using the same Python interpreter
    print("Starting FastAPI server...")
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(backend_root),
    )

    # Wait for server to start (readiness check via /health)
    base_url = "http://127.0.0.1:8000"
    print("Waiting for server to start (polling /health)...")
    server_ready = wait_for_server(base_url, max_wait=15)

    if server_ready:
        print("SERVER STARTED")
    else:
        print("SERVER FAILED TO START (or /health did not respond within 15s)")
        if server_process.poll() is not None:
            print(f"Server process exited with code: {server_process.returncode}")
            # Capture any error output
            stdout, stderr = server_process.communicate()
            if stderr:
                print("SERVER STDERR:")
                print(stderr.decode('utf-8', errors='replace'))
            if stdout:
                print("SERVER STDOUT:")
                print(stdout.decode('utf-8', errors='replace'))
        else:
            print("Server process is still running but /health did not respond")
            server_process.terminate()
            server_process.wait()
        return

    try:
        # Verify server independently using GET /health
        print("HEALTH REQUEST START")
        start = time.time()
        try:
            health_resp = requests.get(f"{base_url}/health", timeout=HTTP_TIMEOUT)
            elapsed = time.time() - start
            print(f"HEALTH RESPONSE: status={health_resp.status_code}, elapsed={elapsed:.3f}s, body={health_resp.text}")
            health_ok = health_resp.status_code == 200
        except requests.exceptions.Timeout:
            elapsed = time.time() - start
            print(f"HEALTH RESPONSE: TIMED OUT after {elapsed:.3f}s (timeout={HTTP_TIMEOUT}s)")
            traceback.print_exc()
            health_ok = False
        except requests.exceptions.RequestException as e:
            elapsed = time.time() - start
            print(f"HEALTH RESPONSE: FAILED after {elapsed:.3f}s - {type(e).__name__}: {e}")
            health_ok = False

        if not health_ok:
            print("❌ /health check failed - server startup / test harness / networking issue")
            return

        # Test jobs API (unauthenticated only)
        jobs_success = test_jobs_api()

        if jobs_success:
            print("\n" + "=" * 60)
            print("✅ DIAGNOSTIC: /api/jobs responded successfully")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ DIAGNOSTIC: /api/jobs did not respond successfully")
            print("=" * 60)

    finally:
        # Stop the server
        print("\nStopping server...")
        server_process.terminate()
        server_process.wait()
        print(f"Server process exited with code: {server_process.returncode}")


if __name__ == "__main__":
    main()
