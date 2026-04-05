#!/usr/bin/env python3
"""Import ALL browser data using HackBrowserData.

Automatically extracts:
- Complete browsing history (all Vinted pages visited)
- Session cookies (_vinted_fr_session automatically!)
- Downloads (saved item images)
- LocalStorage (Vinted preferences)

No more manual cookie copying!

Usage:
    # Extract from Chrome
    python scripts/import_browser_data.py --browser chrome

    # Extract from all browsers
    python scripts/import_browser_data.py --all

    # Extract and immediately run import
    python scripts/import_browser_data.py --browser chrome --import

Prerequisites:
    Install HackBrowserData:
    - Windows: Download from https://github.com/moonD4rk/HackBrowserData/releases
    - Or: go install github.com/moonD4rk/HackBrowserData@latest
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.extractors.hackbrowserdata_extractor import HackBrowserDataExtractor


def main():
    parser = argparse.ArgumentParser(description="Import browser data using HackBrowserData")

    parser.add_argument(
        "--browser",
        choices=["chrome", "firefox", "edge", "safari", "opera"],
        help="Browser to extract from"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Extract from all installed browsers"
    )
    parser.add_argument(
        "--import",
        action="store_true",
        dest="run_import",
        help="Immediately import extracted data to Fashion Twin"
    )
    parser.add_argument(
        "--hackbrowserdata-path",
        default="hack-browser-data",
        help="Path to hack-browser-data executable"
    )

    args = parser.parse_args()

    if not args.browser and not args.all:
        parser.print_help()
        print("\nError: Must specify --browser or --all")
        sys.exit(1)

    # Determine which browsers to extract
    browsers = []
    if args.all:
        browsers = ["chrome", "firefox", "edge", "safari", "opera"]
    else:
        browsers = [args.browser]

    # Extract from each browser
    all_data = {}

    for browser in browsers:
        try:
            print(f"\n{'=' * 70}")
            print(f"EXTRACTING FROM {browser.upper()}")
            print("=" * 70)

            extractor = HackBrowserDataExtractor(
                hackbrowserdata_path=args.hackbrowserdata_path
            )

            data = extractor.extract(browser=browser)

            all_data[browser] = data

            print(f"\n✓ {browser.capitalize()} extraction complete:")
            print(f"  History: {len(data['history'])} items")
            print(f"  Cookies: {len(data['cookies'])} items")
            print(f"  Downloads: {len(data['downloads'])} items")
            print(f"  LocalStorage: {len(data['localstorage'])} items")

            # Import if requested
            if args.run_import:
                print(f"\nImporting {browser} data to Fashion Twin...")
                extractor.store(data)
                print("✓ Import complete")

        except FileNotFoundError:
            print(f"\n✗ {browser.capitalize()} not found or HackBrowserData not installed")
            print("  Install: https://github.com/moonD4rk/HackBrowserData/releases")
            continue

        except Exception as e:
            print(f"\n✗ Failed to extract from {browser}: {e}")
            continue

    # Summary
    print("\n" + "=" * 70)
    print("EXTRACTION SUMMARY")
    print("=" * 70)

    total_items = sum(
        len(data['history']) + len(data['cookies']) +
        len(data['downloads']) + len(data['localstorage'])
        for data in all_data.values()
    )

    print(f"\nBrowsers processed: {len(all_data)}")
    print(f"Total items extracted: {total_items}")

    if not args.run_import:
        print("\nTo import this data:")
        for browser in all_data.keys():
            print(f"  python scripts/import_browser_data.py --browser {browser} --import")

    print("\nBENEFITS:")
    print("  ✓ Complete browsing history (every Vinted page visited)")
    print("  ✓ Session cookies extracted (no manual copy needed!)")
    print("  ✓ Preferences from LocalStorage")
    print("  ✓ Download history (favorited items)")


if __name__ == "__main__":
    main()
