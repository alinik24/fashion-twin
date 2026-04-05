#!/usr/bin/env python
"""Tracking session manager CLI.

Usage:
    # Consent management
    python scripts/track_session.py consent enable fashion
    python scripts/track_session.py consent enable all
    python scripts/track_session.py consent disable food
    python scripts/track_session.py consent status

    # Session control
    python scripts/track_session.py start --domain fashion
    python scripts/track_session.py stop
    python scripts/track_session.py status

    # Log signals manually
    python scripts/track_session.py log dwell --item-id 123 --value 15.0
    python scripts/track_session.py log click --item-id 456
    python scripts/track_session.py log offer --item-id 789 --value 25.0
    python scripts/track_session.py log contact --item-id 123
    python scripts/track_session.py log like --item-id 123    # explicit

    # General activity (any domain)
    python scripts/track_session.py activity food view --payload '{"restaurant":"Sketch"}'
    python scripts/track_session.py activity travel search --payload '{"destination":"Tokyo"}'
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tracker import ConsentManager, TrackingSession, ActivityLogger, SignalType


def cmd_consent(args) -> None:
    cm = ConsentManager()
    if args.consent_cmd == "enable":
        cm.enable(args.domain, reason="user request via CLI")
        print(f"✓ Tracking ENABLED for: {args.domain}")
    elif args.consent_cmd == "disable":
        cm.disable(args.domain, reason="user request via CLI")
        print(f"✓ Tracking DISABLED for: {args.domain}")
    elif args.consent_cmd == "status":
        status = cm.status()
        print("\nConsent status:")
        if not status:
            print("  No domains enabled.")
        for domain, enabled in status.items():
            icon = "✓" if enabled else "✗"
            print(f"  {icon} {domain}")


def cmd_start(args) -> None:
    session = TrackingSession()
    if session.active:
        print(f"Session already active: {session.session_id[:8]}… (domain={session.domain})")
        return
    try:
        sid = session.start(domain=args.domain)
        print(f"✓ Tracking session started: {sid[:8]}… (domain={args.domain})")
        print("  Run 'track_session.py stop' when done.")
    except PermissionError as exc:
        print(f"✗ {exc}")
        sys.exit(1)


def cmd_stop(args) -> None:
    session = TrackingSession()
    if not session.active:
        print("No active session.")
        return
    sid = session.stop()
    print(f"✓ Session stopped: {sid[:8] if sid else '—'}")


def cmd_status(args) -> None:
    session = TrackingSession()
    if session.active:
        s = session._state
        print(f"\n● Active session: {s.session_id[:8]}…")
        print(f"  Domain    : {s.domain}")
        print(f"  Started   : {s.started_at}")
        print(f"  Signals   : {s.signal_count}")
    else:
        print("○ No active tracking session.")

    cm = ConsentManager()
    print("\nConsent:", json.dumps(cm.status(), indent=2))


def cmd_log(args) -> None:
    session = TrackingSession()
    if not session.active:
        print("⚠ No active session — signal logged to DB directly.")
        # Start a transient session
        try:
            session.start(domain="fashion")
        except PermissionError as exc:
            print(f"✗ {exc}")
            return

    sig = session.log(
        signal_type=args.signal_type,
        item_id=args.item_id,
        value=args.value,
        context=json.loads(args.context) if args.context else {},
    )
    session.flush()
    print(f"✓ Logged: {sig.signal_type} item={sig.item_id} value={sig.value} reward={sig.reward:+.2f}")


def cmd_activity(args) -> None:
    logger = ActivityLogger()
    payload = json.loads(args.payload) if args.payload else {}
    event = logger.log(
        domain=args.domain,
        activity_type=args.activity_type,
        payload=payload,
        source_url=args.url,
    )
    if event:
        print(f"✓ Activity logged: {args.domain}/{args.activity_type}")
    else:
        print(f"✗ Consent not granted for domain '{args.domain}'")
        print(f"  Enable with: python scripts/track_session.py consent enable {args.domain}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fashion Twin tracking session manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # consent
    c = sub.add_parser("consent", help="Manage tracking consent")
    c.add_argument("consent_cmd", choices=["enable", "disable", "status"])
    c.add_argument("domain", nargs="?", default="fashion")

    # start
    s = sub.add_parser("start", help="Start a tracking session")
    s.add_argument("--domain", default="fashion")

    # stop
    sub.add_parser("stop", help="Stop active tracking session")

    # status
    sub.add_parser("status", help="Show session and consent status")

    # log
    l = sub.add_parser("log", help="Log a behavioral signal")
    l.add_argument("signal_type", choices=[e.value for e in SignalType])
    l.add_argument("--item-id", type=int, default=None)
    l.add_argument("--value", type=float, default=None, help="Numeric value (seconds, amount)")
    l.add_argument("--context", default=None, help="JSON context dict")

    # activity
    a = sub.add_parser("activity", help="Log a general activity (any domain)")
    a.add_argument("domain", help="Domain: fashion|food|travel|tech|…")
    a.add_argument("activity_type", help="Type: browse|search|view|purchase|…")
    a.add_argument("--payload", default=None, help="JSON payload")
    a.add_argument("--url", default=None, help="Source URL")

    args = parser.parse_args()

    dispatch = {
        "consent": cmd_consent,
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "log": cmd_log,
        "activity": cmd_activity,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
