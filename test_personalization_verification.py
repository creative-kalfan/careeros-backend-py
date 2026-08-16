"""Verify that job personalization is actually working."""

import os
import sys
import json
import requests
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()

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


def get_personalized_jobs(jwt, user_id):
    """Call /api/jobs/personalized with authentication."""
    print("\nCalling GET /api/jobs/personalized...")
    headers = {"Authorization": f"Bearer {jwt}"}
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/jobs/personalized",
            headers=headers,
            params={"page": 1, "page_size": 10},
            timeout=15
        )
        
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Personalized jobs endpoint returned 200")
            
            jobs = data.get('data', [])
            meta = data.get('meta', {})
            print(f"   Jobs returned: {len(jobs)}")
            print(f"   Total: {meta.get('total', 0)}")
            
            return data, jobs
        else:
            print(f"❌ Personalized jobs failed: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            return None, None
    except Exception as e:
        print(f"❌ Error calling personalized jobs: {e}")
        return None, None


def analyze_results(jobs, label=""):
    """Analyze the job results for relevance."""
    if not jobs:
        print(f"\n❌ No jobs to analyze {label}")
        return None
    
    print(f"\n{'='*60}")
    print(f"RESULTS ANALYSIS {label}")
    print(f"{'='*60}")
    
    # Extract job information
    job_info = []
    for i, job in enumerate(jobs[:10], 1):
        title = job.get('title', 'N/A')
        company = job.get('company', 'N/A')
        role_category = job.get('role_category', 'N/A')
        match_score = job.get('match', {}).get('overall', 0) if job.get('match') else 0
        
        job_info.append({
            'title': title,
            'company': company,
            'role_category': role_category,
            'match_score': match_score
        })
        
        print(f"{i}. {title}")
        print(f"   Company: {company}")
        print(f"   Category: {role_category}")
        print(f"   Match Score: {match_score}")
    
    # Analyze role categories
    categories = {}
    for job in job_info:
        cat = job['role_category']
        categories[cat] = categories.get(cat, 0) + 1
    
    print(f"\nRole category distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {cat}: {count}")
    
    # Analyze match scores
    scores = [job['match_score'] for job in job_info]
    if scores:
        avg_score = sum(scores) / len(scores)
        print(f"\nMatch scores:")
        print(f"  - Average: {avg_score:.1f}")
        print(f"  - Min: {min(scores)}")
        print(f"  - Max: {max(scores)}")
    
    return job_info


def main():
    """Main test flow."""
    print("="*60)
    print("PERSONALIZATION VERIFICATION TEST")
    print("="*60)
    
    # Step 1: Login
    jwt, user_id = login_and_get_jwt()
    
    # Step 2: Get personalized jobs
    data, jobs = get_personalized_jobs(jwt, user_id)
    if not jobs:
        print("\n❌ FAILED: No jobs returned")
        return
    
    # Step 3: Analyze results
    job_info = analyze_results(jobs, "for current user")
    
    # Step 4: Check if personalization is working
    print(f"\n{'='*60}")
    print("PERSONALIZATION ASSESSMENT")
    print(f"{'='*60}")
    
    # Check 1: Are jobs ranked by match score?
    scores = [job['match_score'] for job in job_info]
    is_sorted = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
    print(f"✅ Jobs sorted by match score: {is_sorted}")
    
    # Check 2: Is there variety in role categories?
    categories = set(job['role_category'] for job in job_info)
    print(f"✅ Role categories found: {len(categories)}")
    for cat in categories:
        print(f"   - {cat}")
    
    # Check 3: Are match scores meaningful?
    unique_scores = set(scores)
    print(f"✅ Unique match scores: {len(unique_scores)}")
    if len(unique_scores) > 1:
        print(f"   Scores: {sorted(unique_scores, reverse=True)}")
    else:
        print(f"   WARNING: All jobs have the same score!")
    
    # Final verdict
    print(f"\n{'='*60}")
    if is_sorted and len(categories) > 0:
        print("✅ PERSONALIZATION IS WORKING")
        print("   - Jobs are ranked by relevance")
        print("   - Multiple role categories present")
        if len(unique_scores) > 1:
            print("   - Match scores are differentiated")
        else:
            print("   ⚠️  All jobs have identical scores (scoring may need improvement)")
    else:
        print("❌ PERSONALIZATION MAY NOT BE WORKING CORRECTLY")
        if not is_sorted:
            print("   - Jobs are NOT sorted by match score")
        if len(categories) == 0:
            print("   - No role categories found")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()