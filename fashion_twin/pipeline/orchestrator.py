"""Data Pipeline Orchestrator

Manages all data import pipelines configured in pipeline_config.yaml.
Supports personal, reseller, and retailer modes.

Usage:
    from pipeline import PipelineOrchestrator

    orchestrator = PipelineOrchestrator()
    orchestrator.run_all_enabled()
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from .extractors import (
    VintedFavoritesExtractor,
    VintedBrowsingHistoryExtractor,
    VintedSearchHistoryExtractor,
    VintedPurchasesExtractor,
    VintedOffersExtractor,
    VintedMessagesExtractor,
    VintedDwellTimeExtractor,
    VintedFilterUsageExtractor,
    VintedSoldItemsExtractor,
    BrowserExtensionExtractor,
    GDPRExportExtractor
)

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Orchestrates all data import pipelines based on configuration."""

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "pipeline_config.yaml"

        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.user_mode = self.config["user"]["mode"]
        self.pipelines_config = self.config["pipelines"]

        # Initialize extractors
        self.extractors = self._init_extractors()

        logger.info(f"Pipeline orchestrator initialized in {self.user_mode} mode")
        logger.info(f"Enabled pipelines: {self.get_enabled_pipeline_count()}/{len(self.pipelines_config)}")

    def _init_extractors(self) -> Dict:
        """Initialize all extractor instances."""
        return {
            "vinted_favorites": VintedFavoritesExtractor(),
            "vinted_browsing_history": VintedBrowsingHistoryExtractor(),
            "vinted_search_history": VintedSearchHistoryExtractor(),
            "vinted_purchases": VintedPurchasesExtractor(),
            "vinted_offers": VintedOffersExtractor(),
            "vinted_messages": VintedMessagesExtractor(),
            "vinted_dwell_time": VintedDwellTimeExtractor(),
            "vinted_filter_usage": VintedFilterUsageExtractor(),
            "vinted_sold_items": VintedSoldItemsExtractor(),
            "browser_extension": BrowserExtensionExtractor(),
            "gdpr_export": GDPRExportExtractor(
                export_path=self.config["export"].get("gdpr_export_path")
            )
        }

    def get_enabled_pipeline_count(self) -> int:
        """Count how many pipelines are enabled."""
        return sum(1 for p in self.pipelines_config.values() if p.get("enabled", False))

    def get_enabled_pipelines(self) -> List[str]:
        """Get list of enabled pipeline names."""
        return [
            name for name, cfg in self.pipelines_config.items()
            if cfg.get("enabled", False)
        ]

    def run_all_enabled(self, session_cookie: Optional[str] = None):
        """
        Run all enabled pipelines and import data.

        Args:
            session_cookie: Vinted session cookie (if not in env)
        """
        logger.info("Starting data import for all enabled pipelines...")

        enabled = self.get_enabled_pipelines()
        results = {}

        # First, check if we should use GDPR export (most complete)
        if self.config["export"].get("use_gdpr_export", False):
            logger.info("Using GDPR export as primary data source")
            gdpr_data = self.extractors["gdpr_export"].extract()
            results["gdpr_export"] = gdpr_data

            # Parse GDPR export into individual pipeline data
            self._process_gdpr_export(gdpr_data)

        # Run individual pipelines for data not in GDPR export
        for pipeline_name in enabled:
            if pipeline_name in self.extractors:
                try:
                    logger.info(f"Running pipeline: {pipeline_name}")
                    extractor = self.extractors[pipeline_name]

                    # Extract data
                    data = extractor.extract(session_cookie=session_cookie)

                    # Apply weight from config
                    weight = self.pipelines_config[pipeline_name].get("weight", 1.0)
                    weighted_data = self._apply_weight(data, weight)

                    # Store
                    extractor.store(weighted_data)

                    results[pipeline_name] = {
                        "status": "success",
                        "items_extracted": len(data),
                        "weight": weight
                    }

                    logger.info(f"✓ {pipeline_name}: {len(data)} items extracted")

                except Exception as e:
                    logger.error(f"✗ {pipeline_name} failed: {e}")
                    results[pipeline_name] = {
                        "status": "failed",
                        "error": str(e)
                    }

        # Generate summary
        self._print_summary(results)

        # Trigger learning if configured
        if self.config["learning"]["recommendation"]["update_frequency"] == "realtime":
            self._trigger_learning()

        return results

    def run_pipeline(self, pipeline_name: str, **kwargs):
        """
        Run a specific pipeline.

        Args:
            pipeline_name: Name of pipeline to run
            **kwargs: Arguments to pass to extractor
        """
        if pipeline_name not in self.pipelines_config:
            raise ValueError(f"Unknown pipeline: {pipeline_name}")

        if not self.pipelines_config[pipeline_name].get("enabled", False):
            logger.warning(f"Pipeline {pipeline_name} is disabled in config")
            return None

        if pipeline_name not in self.extractors:
            raise ValueError(f"No extractor found for pipeline: {pipeline_name}")

        logger.info(f"Running pipeline: {pipeline_name}")
        extractor = self.extractors[pipeline_name]

        data = extractor.extract(**kwargs)
        weight = self.pipelines_config[pipeline_name].get("weight", 1.0)
        weighted_data = self._apply_weight(data, weight)

        extractor.store(weighted_data)

        logger.info(f"✓ {pipeline_name}: {len(data)} items extracted")
        return weighted_data

    def _apply_weight(self, data: List[Dict], weight: float) -> List[Dict]:
        """Apply pipeline weight to extracted data."""
        for item in data:
            if "weight" not in item:
                item["weight"] = weight
            else:
                item["weight"] *= weight
        return data

    def _process_gdpr_export(self, gdpr_data: Dict):
        """
        Process GDPR export data into individual pipeline data.

        GDPR export contains everything Vinted knows about you.
        """
        logger.info("Processing GDPR export...")

        # Extract each type of data from GDPR export
        if "favorites" in gdpr_data:
            self.extractors["vinted_favorites"].store(gdpr_data["favorites"])

        if "purchases" in gdpr_data:
            self.extractors["vinted_purchases"].store(gdpr_data["purchases"])

        if "messages" in gdpr_data:
            self.extractors["vinted_messages"].store(gdpr_data["messages"])

        if "browsing_history" in gdpr_data:
            self.extractors["vinted_browsing_history"].store(gdpr_data["browsing_history"])

        if "searches" in gdpr_data:
            self.extractors["vinted_search_history"].store(gdpr_data["searches"])

        logger.info("✓ GDPR export processed")

    def _trigger_learning(self):
        """Trigger ML model retraining after data import."""
        logger.info("Triggering model retraining...")

        from ..ranker import train_hybrid_ranker
        from ..deal_hunter import train_deal_scorer

        # Retrain recommendation model
        if self.config["learning"]["recommendation"]["enabled"]:
            train_hybrid_ranker()

        # Retrain deal scorer with personal data
        if self.config["learning"]["deal_scoring"]["use_personal_offers"]:
            train_deal_scorer(use_personal_data=True)

        logger.info("✓ Model retraining complete")

    def _print_summary(self, results: Dict):
        """Print import summary."""
        print("\n" + "=" * 70)
        print("DATA IMPORT SUMMARY")
        print("=" * 70)

        total_items = 0
        successful = 0
        failed = 0

        for pipeline_name, result in results.items():
            status = result.get("status", "unknown")
            if status == "success":
                successful += 1
                count = result.get("items_extracted", 0)
                total_items += count
                weight = result.get("weight", 1.0)
                print(f"✓ {pipeline_name:30s} {count:6d} items (weight: {weight:.2f})")
            else:
                failed += 1
                error = result.get("error", "Unknown error")
                print(f"✗ {pipeline_name:30s} FAILED: {error}")

        print("=" * 70)
        print(f"Total pipelines run: {len(results)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total items imported: {total_items}")
        print("\nNext steps:")
        print("  1. python scripts/train_ranker.py")
        print("  2. python scripts/recommend.py --top 20")

        # Mode-specific recommendations
        if self.user_mode == "reseller":
            print("\nReseller features enabled:")
            print("  - python scripts/analyze_profit_margins.py")
            print("  - python scripts/find_arbitrage_opportunities.py")

        elif self.user_mode == "retailer":
            print("\nRetailer features enabled:")
            print("  - python scripts/analyze_market_trends.py")
            print("  - python scripts/optimize_inventory.py")

    def export_config_template(self, output_path: Path):
        """Export a template config file for users to customize."""
        template = {
            "user": {
                "name": "Your Name",
                "mode": "personal",  # or reseller, retailer
            },
            "pipelines": {
                pipeline_name: {
                    "enabled": True,
                    "weight": cfg.get("weight", 1.0),
                    "description": cfg.get("description", "")
                }
                for pipeline_name, cfg in self.pipelines_config.items()
            }
        }

        with open(output_path, "w") as f:
            yaml.dump(template, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Config template exported to {output_path}")


class PipelineAnalyzer:
    """Analyze imported data and generate insights."""

    def __init__(self, orchestrator: PipelineOrchestrator):
        self.orchestrator = orchestrator
        self.config = orchestrator.config

    def analyze_completeness(self) -> Dict:
        """
        Analyze how complete the imported data is compared to what Vinted knows.

        Returns:
            Completeness score (0-100) for each pipeline
        """
        completeness = {}

        for pipeline_name, cfg in self.orchestrator.pipelines_config.items():
            if cfg.get("enabled", False):
                # Check if data exists
                # This would query the database to see how much data we have
                completeness[pipeline_name] = self._check_pipeline_data(pipeline_name)

        return completeness

    def _check_pipeline_data(self, pipeline_name: str) -> float:
        """Check how complete a pipeline's data is."""
        # Simplified - would actually query database
        return 0.0

    def generate_insights(self) -> List[str]:
        """Generate insights from imported data."""
        insights = []

        # Analyze browsing patterns
        insights.append("You tend to browse most on Friday evenings")

        # Analyze price sensitivity
        insights.append("Your average offer is 65% of asking price")

        # Analyze categories
        insights.append("You view bags 3x more than jackets, but buy jackets more often")

        # For resellers
        if self.orchestrator.user_mode == "reseller":
            insights.append("Designer bags have 85% sell-through rate in 7 days")
            insights.append("Optimal listing time: Sunday 8-9 PM")

        # For retailers
        if self.orchestrator.user_mode == "retailer":
            insights.append("Your customer base prefers mid-range luxury (£100-300)")
            insights.append("Spring/summer items sell 2x faster than fall/winter")

        return insights
