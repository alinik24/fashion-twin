#!/usr/bin/env python
"""Manage style profile and rules.

Usage:
    # Interactive setup
    python scripts/manage_profile.py setup

    # View profile
    python scripts/manage_profile.py show
    python scripts/manage_profile.py summary      # LLM-generated summary

    # Set attributes
    python scripts/manage_profile.py set preferred_size M
    python scripts/manage_profile.py set liked_brand Sandro
    python scripts/manage_profile.py set blocked_material polyester

    # Rules
    python scripts/manage_profile.py rules list
    python scripts/manage_profile.py rules add block brand in "Shein,Boohoo"
    python scripts/manage_profile.py rules add prefer condition eq new_with_tags --delta 1.5
    python scripts/manage_profile.py rules add block material contains polyester
    python scripts/manage_profile.py rules delete 3
    python scripts/manage_profile.py rules preset sustainable
    python scripts/manage_profile.py rules preset luxury_only
    python scripts/manage_profile.py rules preset budget
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from prelearning import StyleProfileManager, RulesEngine


def cmd_setup(args) -> None:
    pm = StyleProfileManager()
    pm.run_interactive_setup()


def cmd_show(args) -> None:
    pm = StyleProfileManager()
    profile = pm.to_dict()
    if not profile:
        print("No style profile set. Run: python scripts/manage_profile.py setup")
        return
    print("\nStyle Profile:")
    print(json.dumps(profile, indent=2, ensure_ascii=False))


def cmd_summary(args) -> None:
    pm = StyleProfileManager()
    print("\n" + pm.generate_summary())


def cmd_set(args) -> None:
    pm = StyleProfileManager()
    pm.set(attribute=args.attribute, value=args.value, source="explicit")
    print(f"✓ Set {args.attribute} = {args.value}")


def cmd_rules(args) -> None:
    engine = RulesEngine()

    if args.rules_cmd == "list":
        rules = engine.list_rules()
        if not rules:
            print("No active rules.")
            return
        print(f"\n{'ID':>4}  {'Type':10s}  {'Field':20s}  {'Op':12s}  {'Value':30s}  {'Delta':>6}")
        print("─" * 90)
        for r in rules:
            print(f"  {r['id']:2d}  {r['rule_type']:10s}  {r['field']:20s}  "
                  f"{r['operator']:12s}  {r['value']:30s}  {float(r['reward_delta'] or 0):+.1f}")

    elif args.rules_cmd == "add":
        rule_id = engine.add_rule(
            rule_type=args.rule_type,
            field=args.field,
            operator=args.operator,
            value=args.value,
            reward_delta=args.delta or 0.0,
        )
        print(f"✓ Rule #{rule_id} added: {args.rule_type} {args.field} {args.operator} {args.value}")

    elif args.rules_cmd == "delete":
        engine.delete_rule(args.rule_id)
        print(f"✓ Rule #{args.rule_id} deleted")

    elif args.rules_cmd == "preset":
        engine.apply_preset(args.preset_name)
        print(f"✓ Preset '{args.preset_name}' applied")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage style profile and rules")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Interactive profile setup wizard")
    sub.add_parser("show", help="Show current profile")
    sub.add_parser("summary", help="LLM-generated profile summary")

    s = sub.add_parser("set", help="Set a profile attribute")
    s.add_argument("attribute")
    s.add_argument("value")

    r = sub.add_parser("rules", help="Manage scoring rules")
    rsub = r.add_subparsers(dest="rules_cmd", required=True)

    rsub.add_parser("list")

    ra = rsub.add_parser("add")
    ra.add_argument("rule_type", choices=["block", "require", "prefer", "downrank", "avoid_if"])
    ra.add_argument("field")
    ra.add_argument("operator")
    ra.add_argument("value")
    ra.add_argument("--delta", type=float, default=0.0)

    rd = rsub.add_parser("delete")
    rd.add_argument("rule_id", type=int)

    rp = rsub.add_parser("preset")
    rp.add_argument("preset_name", choices=["sustainable", "luxury_only", "budget"])

    args = parser.parse_args()
    dispatch = {
        "setup": cmd_setup,
        "show": cmd_show,
        "summary": cmd_summary,
        "set": cmd_set,
        "rules": cmd_rules,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
