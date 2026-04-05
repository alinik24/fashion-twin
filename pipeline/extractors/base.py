"""Base Extractor Class

All extractors inherit from this and implement extract() and store().
"""

from abc import ABC, abstractmethod
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Base class for all data extractors."""

    def __init__(self):
        self.name = self.__class__.__name__
        logger.debug(f"Initialized {self.name}")

    @abstractmethod
    def extract(self, **kwargs) -> List[Dict]:
        """
        Extract data from source.

        Returns:
            List of extracted data items
        """
        pass

    @abstractmethod
    def store(self, data: List[Dict]):
        """
        Store extracted data in database.

        Args:
            data: Extracted data to store
        """
        pass

    def validate(self, data: List[Dict]) -> bool:
        """
        Validate extracted data before storing.

        Args:
            data: Data to validate

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(data, list):
            logger.error(f"{self.name}: Data must be a list")
            return False

        if len(data) == 0:
            logger.warning(f"{self.name}: No data extracted")
            return True  # Empty is valid

        # Check first item has required fields
        if not isinstance(data[0], dict):
            logger.error(f"{self.name}: Data items must be dicts")
            return False

        return True

    def transform(self, raw_data: List[Dict]) -> List[Dict]:
        """
        Transform raw extracted data into standardized format.

        Args:
            raw_data: Raw data from source

        Returns:
            Transformed data
        """
        # Default: no transformation
        return raw_data

    def enrich(self, data: List[Dict]) -> List[Dict]:
        """
        Enrich data with additional information.

        Args:
            data: Data to enrich

        Returns:
            Enriched data
        """
        # Default: no enrichment
        return data
