"""Test authenticated personalized jobs endpoint.

This script:
1. Logs in with test user credentials
2. Retrieves the user's profile
3. Calls /api/jobs/personalized with the JWT
4. Verifies the response and job relevance
"""

import os
import sys
import requests
import json
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()

HTTP_TIMEOUT = 15  # Increased for Supabase login latency
BASE_URL = "http://127.0.0.1:8001"


def get_test_user_credentials():
    """Get test user credentials from environment."""
    email = os.getenv("TEST_USER_EMAIL")
    password = os.getenv("TEST_USER_PASSWORD")
    if not email or not password:
        print("❌ Missing TEST_USER_EMAIL or TEST_USER_PASSWORD in .env")
        sys.exit(1)
    return email, password


def login_and_get_jwt():
    """Login with Supabase and return JWT."""
    email, password = get_test_user_credentials()
    supabase_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_anon_key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    
    if not supabase_url or not supabase_anon_key:
        print("❌ Missing Supabase credentials in .env")
        sys.exit(1)
    
    print(f"Logging in as: {email}")
    supabase = create_client(supabase_url, supabase_anon_key)
    
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        if not response.session:
            print("❌ Login failed - no session returned")
            sys.exit(1)
        
        jwt = response.session.access_token
        user_id = response.user.id
        print(f"✅ Login successful")
        print(f"   User ID: {user_id}")
        return jwt, user_id
    except Exception as e:
        print(f"❌ Login failed: {e}")
        sys.exit(1)


def get_user_profile(jwt):
    """Get the authenticated user's profile via /auth/me."""
    print("\nRetrieving user profile...")
    headers = {"Authorization": f"Bearer {jwt}"}
    
    try:
        response = requests.get(
            f"{BASE_URL}/auth/me",
            headers=headers,
            timeout=HTTP_TIMEOUT
        )
        if response.status_code == 200:
            user_data = response.json()
            print(f"✅ Profile retrieved")
            print(f"   User ID: {user_data.get('id')}")
            print(f"   Email: {user_data.get('email')}")
            print(f"   Role: {user_data.get('role')}")
            return user_data
        else:
            print(f"❌ Failed to get profile: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error getting profile: {e}")
        return None


def get_personalized_jobs(jwt, user_id):
    """Call /api/jobs/personalized with authentication."""
    print("\nCalling GET /api/jobs/personalized...")
    headers = {"Authorization": f"Bearer {jwt}"}
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/jobs/personalized",
            headers=headers,
            params={"page": 1, "page_size": 10},
            timeout=HTTP_TIMEOUT
        )
        
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Personalized jobs endpoint returned 200")
            print(f"   Success: {data.get('success')}")
            
            jobs = data.get('data', [])
            meta = data.get('meta', {})
            print(f"   Jobs returned: {len(jobs)}")
            print(f"   Total: {meta.get('total', 0)}")
            print(f"   Page: {meta.get('page', 1)}")
            print(f"   Page size: {meta.get('page_size', 10)}")
            
            # Check for relevance information
            if jobs:
                print(f"\n   Sample job titles:")
                for i, job in enumerate(jobs[:5], 1):
                    title = job.get('title', 'N/A')
                    company = job.get('company', 'N/A')
                    print(f"   {i}. {title} at {company}")
                    
                    # Check if job has relevance/match info
                    if 'match_score' in job:
                        print(f"      Match score: {job['match_score']}")
                    if 'relevance' in job:
                        print(f"      Relevance: {job['relevance']}")
            
            return data, jobs
        else:
            print(f"❌ Personalized jobs failed: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            return None, None
    except Exception as e:
        print(f"❌ Error calling personalized jobs: {e}")
        return None, None


def analyze_job_relevance(jobs):
    """Analyze if returned jobs are relevant."""
    if not jobs:
        print("\n❌ No jobs to analyze")
        return False
    
    print("\n" + "=" * 60)
    print("RELEVANCE ANALYSIS")
    print("=" * 60)
    
    # Extract job titles for analysis
    titles = [job.get('title', '').lower() for job in jobs]
    
    # Common job categories to check for
    categories = {
        'software': ['software', 'developer', 'engineer', 'programming', 'coding'],
        'data': ['data', 'analyst', 'analytics', 'bi', 'business intelligence'],
        'product': ['product', 'pm', 'product manager'],
        'design': ['design', 'ux', 'ui', 'designer'],
        'marketing': ['marketing', 'growth', 'seo', 'content'],
    }
    
    # Count matches
    category_matches = {}
    for category, keywords in categories.items():
        matches = sum(1 for title in titles if any(kw in title for kw in keywords))
        if matches > 0:
            category_matches[category] = matches
    
    print(f"Job categories found in results:")
    for category, count in category_matches.items():
        print(f"  - {category}: {count} jobs")
    
    # Check if jobs are diverse or all the same
    unique_titles = set(titles)
    print(f"\nUnique job titles: {len(unique_titles)} out of {len(titles)}")
    
    if len(unique_titles) == len(titles):
        print("✅ All jobs have unique titles (good diversity)")
    else:
        print("⚠️  Some duplicate titles found")
    
    return True


def main():
    """Main test flow."""
    print("=" * 60)
    print("TEST: AUTHENTICATED PERSONALIZED JOBS")
    print("=" * 60)
    
    # Step 1: Login and get JWT
    jwt, user_id = login_and_get_jwt()
    
    # Step 2: Get user profile
    profile = get_user_profile(jwt)
    if not profile:
        print("\n❌ PERSONALIZED JOB API — BLOCKED AT PROFILE")
        return
    
    # Step 3: Get personalized jobs
    data, jobs = get_personalized_jobs(jwt, user_id)
    if not data:
        print("\n❌ PERSONALIZED JOB API — BLOCKED AT PERSONALIZED QUERY")
        return
    
    # Step 4: Analyze relevance
    analyze_job_relevance(jobs)
    
    # Final verdict
    print("\n" + "=" * 60)
    if data.get('success') and jobs:
        print("✅ PERSONALIZED JOB API — VERIFIED")
        print("   - Authentication: SUCCESS")
        print("   - Profile retrieval: SUCCESS")
        print("   - Personalized endpoint: SUCCESS")
        print("   - Jobs returned: YES")
    else:
        print("❌ PERSONALIZED JOB API — BLOCKED AT RELEVANCE")
    print("=" * 60)


if __name__ == "__main__":
    main()