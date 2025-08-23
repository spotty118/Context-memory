#!/usr/bin/env python3
"""
Test script to verify the admin views JWT_EXPIRE_MINUTES fix.
This tests that the settings can be accessed without AttributeError.
"""

import sys
import os

# Add the server directory to the Python path
sys.path.insert(0, 'server')

def test_settings_access():
    """Test that we can access JWT_EXPIRE_MINUTES from get_settings()"""
    try:
        from app.core.config import get_settings
        
        # Test direct function call
        settings = get_settings()
        jwt_expire = settings.JWT_EXPIRE_MINUTES
        print(f"✅ Direct access works: JWT_EXPIRE_MINUTES = {jwt_expire}")
        
        # Test multiple calls (should use cached instance)
        settings2 = get_settings()
        assert settings is settings2, "Settings should be cached"
        print("✅ Settings caching works correctly")
        
        # Test the calculation used in views.py
        max_age = get_settings().JWT_EXPIRE_MINUTES * 60
        print(f"✅ Calculation works: max_age = {max_age} seconds")
        
        return True
        
    except AttributeError as e:
        print(f"❌ AttributeError: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_admin_views_import():
    """Test that admin views can be imported without errors"""
    try:
        # This will execute the module-level code
        from app.admin import views
        print("✅ Admin views module imports successfully")
        
        # Check that the functions exist
        assert hasattr(views, 'admin_login')
        assert hasattr(views, 'admin_signup')
        print("✅ Admin login/signup endpoints exist")
        
        return True
        
    except AttributeError as e:
        print(f"❌ AttributeError during import: {e}")
        return False
    except Exception as e:
        print(f"❌ Import error: {e}")
        return False

if __name__ == "__main__":
    print("Testing JWT_EXPIRE_MINUTES fix...")
    print("-" * 50)
    
    # Test 1: Direct settings access
    test1 = test_settings_access()
    print()
    
    # Test 2: Admin views import
    test2 = test_admin_views_import()
    print()
    
    # Summary
    print("-" * 50)
    if test1 and test2:
        print("✅ All tests passed! The fix is working correctly.")
        print("\nNext steps:")
        print("1. Restart the Docker container:")
        print("   docker-compose -f docker-compose.local.yml -p context-memory-gateway restart app")
        print("2. Test the login endpoint at http://localhost:8000/admin/login")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please review the errors above.")
        sys.exit(1)