"""Update test user profile for personalization verification."""

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

def update_test_profile():
    """Update the test user's profile with a specific desired role."""
    email = os.getenv("TEST_USER_EMAIL")
    password = os.getenv("TEST_USER_PASSWORD")
    supabase_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_anon_key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    
    if not all([email, password, supabase_url, supabase_anon_key]):
        print("❌ Missing required environment variables")
        return False
    
    print(f"Updating profile for: {email}")
    
    try:
        # Login
        supabase = create_client(supabase_url, supabase_anon_key)
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if not response.session:
            print("❌ Login failed")
            return False
        
        user_id = response.user.id
        jwt = response.session.access_token
        print(f"✅ Logged in as: {user_id}")
        
        # Update profile with specific desired role
        profile_data = {
            "id": user_id,
            "desired_role": "Software Engineer",
            "skills": ["python", "javascript", "react", "node.js", "sql"],
            "location": "San Francisco",
            "preferred_locations": ["San Francisco", "Remote"],
            "remote_preference": True,
            "preferred_companies": ["Google", "Meta", "Amazon"],
            "salary_expectation_min": 150000,
            "salary_expectation_max": 200000,
            "salary_currency": "USD",
            "experience": "5 years"
        }
        
        # Upsert the profile
        result = supabase.table("profiles").upsert(profile_data).execute()
        
        if result.data:
            print("✅ Profile updated successfully")
            print(f"   Desired role: {profile_data['desired_role']}")
            print(f"   Skills: {profile_data['skills']}")
            print(f"   Location: {profile_data['location']}")
            return True
        else:
            print("❌ Failed to update profile")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = update_test_profile()
    if success:
        print("\n✅ Test profile updated. Now run: python test_personalization_verification.py")
    else:
        print("\n❌ Failed to update test profile")