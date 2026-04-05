#!/usr/bin/env python3
"""Configure and run data import pipelines.

This is the main interface for configuring what data gets imported
and how Fashion Twin learns from it.

Usage:
    # Interactive configuration wizard
    python scripts/configure_pipeline.py --wizard

    # Run all enabled pipelines
    python scripts/configure_pipeline.py --run-all

    # Run specific pipeline
    python scripts/configure_pipeline.py --run vinted_favorites

    # Request GDPR export (shows instructions)
    python scripts/configure_pipeline.py --gdpr-instructions

    # Show current configuration
    python scripts/configure_pipeline.py --show-config

    # Enable reseller mode
    python scripts/configure_pipeline.py --mode reseller

    # Analyze completeness
    python scripts/configure_pipeline.py --analyze
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.orchestrator import PipelineOrchestrator, PipelineAnalyzer
from pipeline.extractors.gdpr_extractor import request_gdpr_export_instructions
import yaml


def configuration_wizard():
    """Interactive wizard to configure pipelines."""
    print("=" * 80)
    print("FASHION TWIN - DATA PIPELINE CONFIGURATION WIZARD")
    print("=" * 80)
    print()

    # Step 1: Choose mode
    print("STEP 1: Choose your mode")
    print("  1. Personal  - For finding deals for yourself")
    print("  2. Reseller  - For buying and reselling items for profit")
    print("  3. Retailer  - For understanding market trends and customer preferences")
    print()

    while True:
        mode_choice = input("Select mode (1-3): ").strip()
        if mode_choice == "1":
            mode = "personal"
            break
        elif mode_choice == "2":
            mode = "reseller"
            break
        elif mode_choice == "3":
            mode = "retailer"
            break
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")

    print(f"\n✓ Mode set to: {mode}\n")

    # Step 2: Data completeness preference
    print("STEP 2: How much data do you want to import?")
    print("  1. Everything (recommended) - Uses GDPR export + all pipelines")
    print("  2. Essential only - Faster, but less accurate recommendations")
    print("  3. Custom - Choose specific pipelines")
    print()

    while True:
        data_choice = input("Select (1-3): ").strip()
        if data_choice in ["1", "2", "3"]:
            break
        print("Invalid choice.")

    # Load config
    config_path = Path(__file__).parent.parent / "config" / "pipeline_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Update mode
    config["user"]["mode"] = mode

    if data_choice == "1":
        # Enable all pipelines
        for pipeline_name in config["pipelines"]:
            config["pipelines"][pipeline_name]["enabled"] = True
        print("\n✓ All pipelines enabled\n")

    elif data_choice == "2":
        # Enable only essential
        essential = [
            "vinted_favorites",
            "vinted_purchases",
            "vinted_search_history",
            "vinted_offers"
        ]
        for pipeline_name in config["pipelines"]:
            config["pipelines"][pipeline_name]["enabled"] = pipeline_name in essential
        print("\n✓ Essential pipelines enabled\n")

    elif data_choice == "3":
        # Custom selection
        print("\nAvailable pipelines:")
        for i, (pipeline_name, pipeline_config) in enumerate(config["pipelines"].items(), 1):
            desc = pipeline_config.get("description", "")
            print(f"  {i:2d}. {pipeline_name:35s} - {desc}")

        print("\nEnter pipeline numbers to enable (comma-separated, or 'all'):")
        selection = input("> ").strip()

        if selection.lower() == "all":
            for pipeline_name in config["pipelines"]:
                config["pipelines"][pipeline_name]["enabled"] = True
        else:
            try:
                indices = [int(x.strip()) - 1 for x in selection.split(",")]
                pipeline_names = list(config["pipelines"].keys())
                for idx in indices:
                    if 0 <= idx < len(pipeline_names):
                        config["pipelines"][pipeline_names[idx]]["enabled"] = True
            except ValueError:
                print("Invalid input. Enabling essential pipelines only.")

    # Step 3: Mode-specific configuration
    if mode == "reseller":
        print("\nSTEP 3: Reseller Configuration")
        print()
        target_margin = input("Target profit margin % (default 30): ").strip() or "30"
        max_investment = input("Max investment per item £ (default 1000): ").strip() or "1000"
        categories = input("Focus categories (comma-separated, e.g. bags,jackets,shoes): ").strip() or "bags,jackets,shoes"

        config["user"]["reseller_config"] = {
            "target_margin": float(target_margin) / 100,
            "max_investment": float(max_investment),
            "focus_categories": [x.strip() for x in categories.split(",")],
            "turnaround_days": 14
        }

    elif mode == "retailer":
        print("\nSTEP 3: Retailer Configuration")
        print()
        store_type = input("Store type (boutique/online/both, default boutique): ").strip() or "boutique"
        inventory_size = input("Inventory size (small/medium/large, default small): ").strip() or "small"

        config["user"]["retailer_config"] = {
            "store_type": store_type,
            "inventory_size": inventory_size,
            "focus_demographics": ["women_25-35", "luxury_seekers"]
        }

    # Save config
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print("\n" + "=" * 80)
    print("CONFIGURATION COMPLETE!")
    print("=" * 80)
    print(f"\nMode: {mode}")
    print(f"Enabled pipelines: {sum(1 for p in config['pipelines'].values() if p.get('enabled', False))}/{len(config['pipelines'])}")
    print(f"\nConfiguration saved to: {config_path}")
    print("\nNext steps:")
    print("  1. Request your GDPR export:")
    print("     python scripts/configure_pipeline.py --gdpr-instructions")
    print()
    print("  2. Run the import:")
    print("     python scripts/configure_pipeline.py --run-all")
    print()
    print("  3. Train recommendations:")
    print("     python scripts/train_ranker.py")
    print()


def show_config():
    """Show current pipeline configuration."""
    config_path = Path(__file__).parent.parent / "config" / "pipeline_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    mode = config["user"]["mode"]
    pipelines = config["pipelines"]

    print("=" * 80)
    print("CURRENT CONFIGURATION")
    print("=" * 80)
    print(f"\nMode: {mode.upper()}")
    print(f"\nEnabled Pipelines ({sum(1 for p in pipelines.values() if p.get('enabled', False))}/{len(pipelines)}):")
    print()

    for pipeline_name, pipeline_config in pipelines.items():
        if pipeline_config.get("enabled", False):
            weight = pipeline_config.get("weight", 1.0)
            desc = pipeline_config.get("description", "")
            print(f"  ✓ {pipeline_name:35s} (weight: {weight:.1f}) - {desc}")

    print("\nDisabled Pipelines:")
    for pipeline_name, pipeline_config in pipelines.items():
        if not pipeline_config.get("enabled", False):
            desc = pipeline_config.get("description", "")
            print(f"  ✗ {pipeline_name:35s} - {desc}")


def run_all_pipelines(session_cookie: str = None):
    """Run all enabled pipelines."""
    print("=" * 80)
    print("RUNNING DATA IMPORT")
    print("=" * 80)
    print()

    orchestrator = PipelineOrchestrator()
    results = orchestrator.run_all_enabled(session_cookie=session_cookie)

    return results


def run_single_pipeline(pipeline_name: str, session_cookie: str = None):
    """Run a specific pipeline."""
    orchestrator = PipelineOrchestrator()
    result = orchestrator.run_pipeline(pipeline_name, session_cookie=session_cookie)
    return result


def analyze_completeness():
    """Analyze how complete the imported data is."""
    print("=" * 80)
    print("DATA COMPLETENESS ANALYSIS")
    print("=" * 80)
    print()

    orchestrator = PipelineOrchestrator()
    analyzer = PipelineAnalyzer(orchestrator)

    completeness = analyzer.analyze_completeness()
    insights = analyzer.generate_insights()

    print("Data Completeness:")
    for pipeline, score in completeness.items():
        print(f"  {pipeline:35s} {score:5.1f}%")

    print("\nInsights:")
    for insight in insights:
        print(f"  • {insight}")


def set_mode(mode: str):
    """Set user mode (personal/reseller/retailer)."""
    if mode not in ["personal", "reseller", "retailer"]:
        print(f"Invalid mode: {mode}. Must be personal, reseller, or retailer.")
        return

    config_path = Path(__file__).parent.parent / "config" / "pipeline_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    config["user"]["mode"] = mode

    # Enable mode-specific pipelines
    if mode == "reseller":
        config["pipelines"]["vinted_sold_items"]["enabled"] = True
        config["pipelines"]["vinted_listing_performance"]["enabled"] = True
        config["learning"]["reseller_intelligence"]["enabled"] = True

    elif mode == "retailer":
        config["pipelines"]["vinted_trending_items"]["enabled"] = True
        config["advanced"]["cohort_analysis"]["enabled"] = True

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"✓ Mode set to: {mode}")
    print(f"✓ Mode-specific pipelines enabled")
    print(f"\nConfiguration saved to: {config_path}")


def main():
    parser = argparse.ArgumentParser(description="Configure and run data import pipelines")

    parser.add_argument("--wizard", action="store_true", help="Run configuration wizard")
    parser.add_argument("--show-config", action="store_true", help="Show current configuration")
    parser.add_argument("--run-all", action="store_true", help="Run all enabled pipelines")
    parser.add_argument("--run", help="Run specific pipeline")
    parser.add_argument("--gdpr-instructions", action="store_true", help="Show GDPR export instructions")
    parser.add_argument("--analyze", action="store_true", help="Analyze data completeness")
    parser.add_argument("--mode", help="Set mode (personal/reseller/retailer)")
    parser.add_argument("--session-cookie", help="Vinted session cookie")

    args = parser.parse_args()

    if args.wizard:
        configuration_wizard()

    elif args.show_config:
        show_config()

    elif args.run_all:
        run_all_pipelines(session_cookie=args.session_cookie)

    elif args.run:
        run_single_pipeline(args.run, session_cookie=args.session_cookie)

    elif args.gdpr_instructions:
        request_gdpr_export_instructions()

    elif args.analyze:
        analyze_completeness()

    elif args.mode:
        set_mode(args.mode)

    else:
        parser.print_help()
        print("\nTip: Run --wizard for interactive setup")


if __name__ == "__main__":
    main()
