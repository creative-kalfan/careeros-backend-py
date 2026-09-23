"""Probe production Render backend for health + crawl status."""
import json
import urllib.request

BASE = "https://career-os-kr9m.onrender.com"


def get(path, timeout=30):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            return resp.status, body
    except Exception as e:
        return None, str(e)


def main():
    for path in ["/health", "/version", "/dev/arq/crawl-status", "/dev/arq/provider-metrics"]:
        status, body = get(path)
        print(f"\n=== {path} -> {status} ===")
        if status and body:
            try:
                data = json.loads(body)
                print(json.dumps(data, indent=2, default=str)[:6000])
            except Exception:
                print(body[:3000])
        else:
            print(body)


if __name__ == "__main__":
    main()
