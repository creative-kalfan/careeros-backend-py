"""Real authenticated personalization verification with actual profile updates."""

import os
import sys
import json
import time
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

BASE_URL = "http://127.0.0.1:8000"


def get_test_user_credentials():
    """Get test user credentials from environment."""
    email = os.getenv("TEST_USER_EMAIL")
    password = os.getenv("TEST_USER_PASSWORD")
    if not email or not password:
        print("❌ Missing TEST_USER_EMAIL or TEST_USER_PASSWORD in .env")
        sys.exit(1)
    return email, password


def get_supabase_credentials():
    """Get Supabase credentials."""
    supabase_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_anon_key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_anon_key:
        print("❌ Missing Supabase credentials in .env")
        sys.exit(1)
    return supabase_url, supabase_anon_key


def login_and_get_jwt():
    """Login with Supabase and return JWT."""
    email, password = get_test_user_credentials()
    supabase_url, supabase_anon_key = get_supabase_credentials()
    
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
        return jwt, user_id, supabase_url, supabase_anon_key
    except Exception as e:
        print(f"❌ Login failed: {e}")
        sys.exit(1)


def update_profile_via_api(jwt, desired_role):
    """Update profile using the new Python backend profile API."""
    print(f"\n{'='*60}")
    print(f"UPDATING PROFILE VIA API: desired_role = '{desired_role}'")
    print(f"{'='*60}")
    
    headers = {"Authorization": f"Bearer {jwt}"}
    
    # Only send the desired_role field to keep it simple
    profile_data = {
        "desired_role": desired_role,
    }
    
    try:
        response = requests.patch(
            f"{BASE_URL}/api/profile/me",
            headers=headers,
            json=profile_data,
            timeout=15
        )
        
        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Profile updated successfully via API")
            print(f"   Desired role: {data['data']['desired_role']}")
            return True
        else:
            print(f"❌ Profile update failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error updating profile: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_profile_via_api(jwt):
    """Get profile via the API."""
    print(f"\nVerifying profile via API...")
    
    headers = {"Authorization": f"Bearer {jwt}"}
    
    try:
        response = requests.get(
            f"{BASE_URL}/api/profile/me",
            headers=headers,
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            profile = data.get('data', {})
            print(f"✅ Profile retrieved via API")
            print(f"   Desired role: {profile.get('desired_role')}")
            print(f"   Skills: {profile.get('skills', [])}")
            return profile
        else:
            print(f"❌ Failed to get profile: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error getting profile: {e}")
        return None


def get_personalized_jobs(jwt, label=""):
    """Call /api/jobs/personalized with authentication."""
    print(f"\n{'='*60}")
    print(f"CALLING /api/jobs/personalized {label}")
    print(f"{'='*60}")
    
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


def analyze_job_results(jobs, label=""):
    """Analyze job results for relevance."""
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
        print(f"  - Unique values: {len(set(scores))}")
    
    return job_info


def check_relevance(job_info, expected_category, label=""):
    """Check if jobs are relevant to expected category."""
    print(f"\n{'='*60}")
    print(f"RELEVANCE CHECK {label}")
    print(f"{'='*60}")
    
    if not job_info:
        print("❌ No jobs to check")
        return False
    
    # Count relevant jobs
    relevant_count = sum(1 for job in job_info if job['role_category'] == expected_category)
    total_count = len(job_info)
    relevance_percentage = (relevant_count / total_count * 100) if total_count > 0 else 0
    
    print(f"Expected category: {expected_category}")
    print(f"Relevant jobs: {relevant_count}/{total_count} ({relevance_percentage:.1f}%)")
    
    # Check if sorted by score
    scores = [job['match_score'] for job in job_info]
    is_sorted = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
    print(f"Sorted by match score: {is_sorted}")
    
    # Check score diversity
    unique_scores = len(set(scores))
    print(f"Unique match scores: {unique_scores}")
    
    is_relevant = relevant_count > 0 and relevance_percentage >= 50
    
    if is_relevant:
        print(f"✅ PASS: Results are relevant to {expected_category}")
    else:
        print(f"❌ FAIL: Results are NOT relevant to {expected_category}")
    
    return is_relevant


def main():
    """Main test flow."""
    print("="*60)
    print("REAL AUTHENTICATED PERSONALIZATION VERIFICATION")
    print("="*60)
    
    # Step 1: Login
    jwt, user_id, supabase_url, supabase_anon_key = login_and_get_jwt()
    
    # Step 2: Get current profile
    print(f"\n{'='*60}")
    print("TEST 1: GET CURRENT PROFILE")
    print(f"{'='*60}")
    
    profile = get_profile_via_api(jwt)
    if not profile:
        print("❌ No profile found")
        return
    
    # Step 3: Update profile to Software Engineer
    print(f"\n{'='*60}")
    print("TEST 2: SOFTWARE ENGINEER PROFILE")
    print(f"{'='*60}")
    
    sw_eng_update_success = update_profile_via_api(jwt, "Software Engineer")
    
    if sw_eng_update_success:
        # Verify profile was updated
        profile = get_profile_via_api(jwt)
        if profile and profile.get('desired_role') == "Software Engineer":
            print("✅ Profile verified: desired_role = 'Software Engineer'")
        else:
            print("❌ Profile verification failed")
        
        # Small delay to ensure profile is updated
        time.sleep(1)
        
        # Get personalized jobs for Software Engineer
        data2, jobs2 = get_personalized_jobs(jwt, "(Software Engineer profile)")
        if jobs2:
            job_info2 = analyze_job_results(jobs2, "(Software Engineer profile)")
            sw_eng_relevant = check_relevance(job_info2, "Software Engineering", "Software Engineer")
        else:
            print("❌ No jobs returned for Software Engineer profile")
            job_info2 = None
            sw_eng_relevant = False
    else:
        print("❌ Failed to update profile to Software Engineer")
        job_info2 = None
        sw_eng_relevant = False
    
    # Step 4: Update profile to Data Scientist
    print(f"\n{'='*60}")
    print("TEST 3: DATA SCIENTIST PROFILE")
    print(f"{'='*60}")
    
    ds_update_success = update_profile_via_api(jwt, "Data Scientist")
    
    if ds_update_success:
        # Verify profile was updated
        profile = get_profile_via_api(jwt)
        if profile and profile.get('desired_role') == "Data Scientist":
            print("✅ Profile verified: desired_role = 'Data Scientist'")
        else:
            print("❌ Profile verification failed")
        
        # Small delay to ensure profile is updated
        time.sleep(1)
        
        # Get personalized jobs for Data Scientist
        data3, jobs3 = get_personalized_jobs(jwt, "(Data Scientist profile)")
        if jobs3:
            job_info3 = analyze_job_results(jobs3, "(Data Scientist profile)")
            ds_relevant = check_relevance(job_info3, "Data Science", "Data Scientist")
        else:
            print("❌ No jobs returned for Data Scientist profile")
            job_info3 = None
            ds_relevant = False
    else:
        print("❌ Failed to update profile to Data Scientist")
        job_info3 = None
        ds_relevant = False
    
    # Step 5: Compare feeds
    print(f"\n{'='*60}")
    print("TEST 4: FEED COMPARISON")
    print(f"{'='*60}")
    
    if job_info2 and job_info3:
        # Compare titles
        titles2 = {job['title'] for job in job_info2}
        titles3 = {job['title'] for job in job_info3}
        
        overlap = titles2 & titles3
        feeds_differ = len(overlap) < min(len(job_info2), len(job_info3))
        
        print(f"Software Engineer jobs: {len(job_info2)}")
        print(f"Data Scientist jobs: {len(job_info3)}")
        print(f"Overlap: {len(overlap)} jobs")
        
        if feeds_differ:
            print(f"✅ Feeds are meaningfully different")
        else:
            print(f"⚠️  Feeds are identical or very similar")
    else:
        print("❌ Cannot compare feeds - missing data")
        feeds_differ = False
    
    # Step 6: Test empty profile
    print(f"\n{'='*60}")
    print("TEST 5: EMPTY PROFILE")
    print(f"{'='*60}")
    
    update_profile_via_api(jwt, "")
    time.sleep(1)
    
    data4, jobs4 = get_personalized_jobs(jwt, "(empty profile)")
    if jobs4:
        job_info4 = analyze_job_results(jobs4, "(empty profile)")
        empty_works = len(jobs4) > 0
    else:
        print("❌ No jobs returned for empty profile")
        job_info4 = None
        empty_works = False
    
    # Final verdict
    print(f"\n{'='*60}")
    print("FINAL VERDICT")
    print(f"{'='*60}")
    
    print(f"\n✅ Profile update via API: {'PASS' if sw_eng_update_success and ds_update_success else 'FAIL'}")
    print(f"✅ Software Engineer profile returns jobs: {'PASS' if job_info2 else 'FAIL'}")
    print(f"✅ Software Engineer results are relevant: {'PASS' if sw_eng_relevant else 'FAIL'}")
    print(f"✅ Data Scientist profile returns jobs: {'PASS' if job_info3 else 'FAIL'}")
    print(f"✅ Data Scientist results are relevant: {'PASS' if ds_relevant else 'FAIL'}")
    print(f"✅ Feeds are meaningfully different: {'PASS' if feeds_differ else 'FAIL'}")
    print(f"✅ Empty profile returns jobs: {'PASS' if empty_works else 'FAIL'}")
    
    if sw_eng_relevant and ds_relevant and feeds_differ and empty_works:
        print(f"\n{'='*60}")
        print("✅ PERSONALIZATION VERIFICATION: PASSED")
        print(f"{'='*60}")
        print("Real authenticated personalization is working correctly!")
    else:
        print(f"\n{'='*60}")
        print("❌ PERSONALIZATION VERIFICATION: FAILED")
        print(f"{'='*60}")
        print("Personalization may not be working as expected")
    
    # Logout
    try:
        supabase.auth.sign_out()
    except:
        pass


if __name__ == "__main__":
    main()