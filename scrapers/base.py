"""Base scraper class. All site scrapers inherit from this."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AuctionItem:
    """Represents a single auction listing."""
    site: str                          # e.g. "rbauction"
    item_id: str                       # unique ID on that site
    title: str
    url: str
    location_city: str = ""
    location_state: str = ""
    location_zip: str = ""
    auction_date: Optional[str] = None # ISO date string or human-readable
    price_estimate: str = ""           # e.g. "$1,200 - $1,800" or "No Reserve"
    image_url: str = ""
    description: str = ""
    matched_terms: list = field(default_factory=list)

    @property
    def uid(self) -> str:
        """Stable unique key for caching."""
        return f"{self.site}::{self.item_id}"

    def to_dict(self) -> dict:
        return {
            "site": self.site,
            "item_id": self.item_id,
            "title": self.title,
            "url": self.url,
            "location_city": self.location_city,
            "location_state": self.location_state,
            "location_zip": self.location_zip,
            "auction_date": self.auction_date,
            "price_estimate": self.price_estimate,
            "image_url": self.image_url,
            "description": self.description,
            "matched_terms": self.matched_terms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AuctionItem":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class BaseScraper(ABC):
    """
    Abstract base class for auction site scrapers.

    Subclasses must implement:
      - login(page)
      - search(page, term) -> list[AuctionItem]

    The `run()` method handles browser lifecycle and calls these in order.
    """

    SITE_ID: str = ""   # must be set in subclass, matches config.yaml `id`
    SITE_NAME: str = "" # human-readable

    def __init__(self, credentials: dict, browser_config: dict):
        """
        Args:
            credentials: dict with keys like 'email', 'password'
            browser_config: dict from config.yaml browser section
        """
        self.email = credentials.get("email", "")
        self.password = credentials.get("password", "")
        self.headless = browser_config.get("headless", True)
        self.slow_mo = browser_config.get("slow_mo_ms", 0)
        self.timeout = browser_config.get("timeout_ms", 30000)
        self._logged_in = False

    @abstractmethod
    def login(self, page) -> bool:
        """
        Navigate to login page and authenticate.

        Args:
            page: Playwright Page object

        Returns:
            True if login succeeded, False otherwise.
        """

    @abstractmethod
    def search(self, page, term: str) -> list:
        """
        Search for `term` and return a list of AuctionItem objects.
        Should only return upcoming/active listings.

        Args:
            page: Playwright Page object (already logged in)
            term: search keyword string

        Returns:
            List of AuctionItem
        """

    def run(self, playwright, search_terms: list[str]) -> list:
        """
        Full browser session: launch -> login -> search all terms -> close.

        Returns:
            Flat list of AuctionItem across all search terms.
        """
        from playwright.sync_api import TimeoutError as PWTimeout

        results = []
        browser = playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.set_default_timeout(self.timeout)

        try:
            logger.info("[%s] Logging in...", self.SITE_NAME)
            ok = self.login(page)
            if not ok:
                logger.warning("[%s] Login failed, skipping.", self.SITE_NAME)
                return []
            self._logged_in = True

            for term in search_terms:
                logger.info("[%s] Searching: %s", self.SITE_NAME, term)
                try:
                    items = self.search(page, term)
                    for item in items:
                        if term not in item.matched_terms:
                            item.matched_terms.append(term)
                    results.extend(items)
                    logger.info("[%s] '%s' -> %d result(s)", self.SITE_NAME, term, len(items))
                except PWTimeout:
                    logger.warning("[%s] Timeout on term '%s'", self.SITE_NAME, term)
                except Exception as exc:
                    logger.warning("[%s] Error on term '%s': %s", self.SITE_NAME, term, exc)

        except Exception as exc:
            logger.error("[%s] Fatal error: %s", self.SITE_NAME, exc)
        finally:
            context.close()
            browser.close()

        # Deduplicate by uid within this site's results
        seen = {}
        for item in results:
            if item.uid not in seen:
                seen[item.uid] = item
            else:
                # Merge matched_terms
                seen[item.uid].matched_terms = list(
                    set(seen[item.uid].matched_terms + item.matched_terms)
                )
        return list(seen.values())
