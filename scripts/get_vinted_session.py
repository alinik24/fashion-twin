#!/usr/bin/env python3
"""
Get Vinted session cookie from Chrome browser

Usage: Run this script, it will extract the session cookie from your Chrome profile.
"""

import sys
import os
import sqlite3
import json
from pathlib import Path

def get_chrome_cookies():
    """Extract Vinted cookies from Chrome browser."""

    # Chrome profile path for Profile 4
    chrome_profile_path = Path(os.getenv('LOCALAPPDATA')) / 'Google' / 'Chrome' / 'User Data' / 'Profile 4'
    cookies_path = chrome_profile_path / 'Network' / 'Cookies'

    if not cookies_path.exists():
        # Try default profile
        chrome_profile_path = Path(os.getenv('LOCALAPPDATA')) / 'Google' / 'Chrome' / 'User Data' / 'Default'
        cookies_path = chrome_profile_path / 'Network' / 'Cookies'

    if not cookies_path.exists():
        print(f"❌ Chrome cookies file not found at: {cookies_path}")
        print("\nAlternative: Login to Vinted and copy the cookie manually:")
        print("1. Open https://www.vinted.de/ in Chrome")
        print("2. Press F12 (DevTools)")
        print("3. Go to Application > Cookies > https://www.vinted.de")
        print("4. Find '_vinted_fr_session' or similar cookie")
        print("5. Copy the value")
        return None

    print(f"[*] Found Chrome cookies at: {cookies_path}")

    try:
        # Copy cookies file (Chrome locks it)
        import shutil
        temp_cookies = cookies_path.parent / 'Cookies_temp'
        shutil.copy2(cookies_path, temp_cookies)

        # Connect to cookies database
        conn = sqlite3.connect(str(temp_cookies))
        cursor = conn.cursor()

        # Query Vinted cookies
        cursor.execute("""
            SELECT name, value, host_key
            FROM cookies
            WHERE host_key LIKE '%vinted%'
        """)

        vinted_cookies = cursor.fetchall()
        conn.close()

        # Clean up temp file
        temp_cookies.unlink()

        if not vinted_cookies:
            print("❌ No Vinted cookies found in Chrome")
            print("\n💡 Make sure you're logged into Vinted in Chrome Profile 4")
            return None

        print(f"\n✅ Found {len(vinted_cookies)} Vinted cookie(s):")
        for name, value, host in vinted_cookies:
            print(f"  - {name} (from {host})")
            if 'session' in name.lower() or 'token' in name.lower():
                print(f"\n🔑 Session cookie found!")
                print(f"Cookie name: {name}")
                print(f"Cookie value: {value[:50]}..." if len(value) > 50 else f"Cookie value: {value}")
                return {name: value}

        return None

    except Exception as e:
        print(f"❌ Error reading cookies: {e}")
        print("\n💡 Try closing Chrome and running this script again")
        return None

def main():
    print("=" * 70)
    print("Vinted Session Cookie Extractor")
    print("=" * 70)

    cookies = get_chrome_cookies()

    if cookies:
        print("\n" + "=" * 70)
        print("✅ SUCCESS!")
        print("=" * 70)
        print("\nAdd this to your .env file:")
        print(f"VINTED_SESSION_COOKIE={list(cookies.values())[0]}")
    else:
        print("\n" + "=" * 70)
        print("Manual steps:")
        print("=" * 70)
        print("1. Open Chrome and go to https://www.vinted.de/")
        print("2. Make sure you're logged in")
        print("3. Press F12 to open DevTools")
        print("4. Go to: Application tab > Storage > Cookies > https://www.vinted.de")
        print("5. Look for cookies like:")
        print("   - _vinted_fr_session")
        print("   - access_token_web")
        print("   - session_id")
        print("6. Copy the cookie value")
        print("7. Add to .env: VINTED_SESSION_COOKIE=<value>")

if __name__ == "__main__":
    main()
