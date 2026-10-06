# ATS Coverage & Probe Report

**Generated:** 2026-10-06  
**Evaluation Principle:** Unauthenticated, keyless, public JSON API only. No credential scraping, no CAPTCHA bypass, no access control evasion. Respect robots.txt and official rate limits.

---

## 1. Summary Matrix

| ATS / Provider | Keyless Public JSON API? | Status | Evidence / Test Details |
| :--- | :---: | :---: | :--- |
| **Workday** | **YES** | **IMPLEMENTED** | Public CxS API `/wday/cxs/{tenant}/{site}/jobs` (POST) and `/job/{externalPath}` (GET). Verified against live enterprise tenants (e.g., Adobe). Returns structured job count, title, reqId, locations, and real `startDate`. |
| **Workable** | **NO** | Rejected | `/api/v3/accounts/{slug}/jobs` returns 404 for standard company slugs; modern accounts use Cloudflare protection, authenticated widget tokens, or customer-specific subdomains requiring API keys. |
| **Recruitee** | **NO** | Rejected | Legacy `/api/offers` endpoint is deprecated/disabled on modern accounts (returns 404 on tested customer slugs). Requires official Partner API token. |
| **Teamtailor** | **NO** | Rejected | Official API `/v1/jobs` returns HTTP 406 / requires Authorization Bearer token. Public career site JSON `/jobs.json` is disabled or returns 0 jobs for public clients. |
| **Zoho Recruit** | **NO** | Rejected | Public REST API `/recruit/v2/public/Job_Openings` returns HTTP 400 Bad Request; requires registered portal name, client auth, or OAuth 2.0 app credentials. |
| **Keka** | **NO** | Rejected | Endpoints like `/api/v1/jobs` return HTTP 404. Keka careers portals are server-side rendered ASP.NET / Angular single-page apps without unauthenticated public listing APIs. |
| **Darwinbox** | **NO** | Rejected | Recruitment portals return HTML/redirects; public unauthenticated JSON endpoint does not exist. |
| **Freshteam** | **NO** | Rejected | `freshworks.freshteam.com/api/job_postings` returns HTTP 503 or requires Freshworks Organization API key. |

---

## 2. Workday CxS API Specification

### 2.1 List Endpoint
- **URL Pattern:** `https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`
- **Method:** `POST`
- **Headers:** `Content-Type: application/json`, standard user agent
- **Payload:**
  ```json
  {
    "appliedFacets": {},
    "limit": 20,
    "offset": 0,
    "searchText": ""
  }
  ```
- **Response Shape:**
  ```json
  {
    "total": 474,
    "jobPostings": [
      {
        "title": "Enterprise Architect",
        "externalPath": "/job/Bangalore/Enterprise-Architect_R169928",
        "locationsText": "2 Locations",
        "postedOn": "Posted Yesterday",
        "bulletFields": ["R169928"]
      }
    ]
  }
  ```

### 2.2 Detail Endpoint
- **URL Pattern:** `https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}`
- **Method:** `GET`
- **Response Shape:**
  ```json
  {
    "jobPostingInfo": {
      "id": "R169928",
      "title": "Enterprise Architect",
      "jobDescription": "<div>...</div>",
      "location": "Bangalore",
      "additionalLocations": ["Noida"],
      "startDate": "2026-10-05",
      "timeType": "Full time",
      "externalUrl": "..."
    }
  }
  ```
- **Date Fidelity:** `startDate` provides the authoritative ISO date (e.g. `2026-10-05`). String phrases like `"Posted Yesterday"` are strictly ignored for `posted_at`.

---

## 3. Policy & Decisions
Only **Workday** meets all reliability, public access, and data hygiene criteria without third-party credentials. Workday adapter is added to the canonical ingestion pipeline. All other investigated platforms require credentials or scraping and are deferred to verified customer integrations or generic crawl fallbacks.
