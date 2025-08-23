#!/usr/bin/env python3
"""Test all admin pages for the Context Memory Gateway."""

import requests
import json

def test_admin_pages():
    base_url = 'http://45.79.198.10:8000'
    session = requests.Session()
    
    print("=" * 60)
    print("Testing Admin Pages - Context Memory Gateway")
    print("=" * 60)
    
    # Test login
    print("\n1. Testing Login...")
    login_data = {
        'username': 'your',
        'password': 'super'
    }
    
    login_resp = session.post(f'{base_url}/admin/login', data=login_data, allow_redirects=False)
    print(f"   Login response: {login_resp.status_code}")
    
    if login_resp.status_code == 302:
        print("   ✓ Login successful (redirected)")
        
        # Check if we got a JWT token in cookies
        if 'admin_token' in session.cookies:
            print("   ✓ JWT token received")
        else:
            print("   ⚠ No JWT token in cookies")
    else:
        print(f"   ✗ Login failed: {login_resp.text[:200]}")
        return
    
    # Test authenticated access to admin pages
    print("\n2. Testing Authenticated Access to Admin Pages...")
    pages = [
        ('/admin/dashboard', 'Dashboard'),
        ('/admin/api-keys', 'API Keys'),
        ('/admin/models', 'Models'),
        ('/admin/settings', 'Settings'),
        ('/admin/workers', 'Workers')
    ]
    
    for path, name in pages:
        resp = session.get(f'{base_url}{path}')
        if resp.status_code == 200:
            # Check if it's actually the page content (not a redirect)
            if '<title>' in resp.text:
                title_start = resp.text.find('<title>') + 7
                title_end = resp.text.find('</title>', title_start)
                title = resp.text[title_start:title_end] if title_end > title_start else 'Unknown'
                print(f"   ✓ {name:15} Status: {resp.status_code}  Title: {title}")
            else:
                print(f"   ✓ {name:15} Status: {resp.status_code}")
        else:
            print(f"   ✗ {name:15} Status: {resp.status_code}")
    
    # Test API key generation endpoint
    print("\n3. Testing API Key Generation...")
    key_data = {
        'name': 'Test Key',
        'workspace_id': 'test-workspace',
        'daily_quota_tokens': 100000,
        'rate_limit_requests': 60
    }
    
    key_resp = session.post(f'{base_url}/admin/api-keys/generate', json=key_data)
    print(f"   Generate API Key response: {key_resp.status_code}")
    
    if key_resp.status_code == 200:
        print("   ✓ API key generation endpoint works")
    else:
        print(f"   ⚠ API key generation issue: {key_resp.text[:200] if key_resp.text else 'No response'}")
    
    # Test logout
    print("\n4. Testing Logout...")
    logout_resp = session.post(f'{base_url}/admin/logout')
    print(f"   Logout response: {logout_resp.status_code}")
    
    # Verify we can't access protected pages after logout
    dashboard_resp = session.get(f'{base_url}/admin/dashboard')
    if dashboard_resp.status_code == 302:
        print("   ✓ Correctly redirected to login after logout")
    else:
        print(f"   ⚠ Unexpected status after logout: {dashboard_resp.status_code}")
    
    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)

if __name__ == "__main__":
    test_admin_pages()
