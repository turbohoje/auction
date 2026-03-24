"""
Scraper for Roller Auction (rollerauction.com).

TODO checklist before this scraper works:
  1. Confirm login flow selectors (see login() method)
  2. Confirm search URL structure and result selectors (see search() method)
  3. Roller Auction appears to be HubSpot-based — search may redirect to
     a specific page or use a built-in site search. Inspect manually.
"""

import logging

from .base import AuctionItem, BaseScraper

logger = logging.getLogger(__name__)

LOGIN_URL   = "https://rollerauction.com/login"    # TODO: verify
SEARCH_URL  = "https://rollerauction.com/search"   # TODO: verify


class RollerAuctionScraper(BaseScraper):
    SITE_ID   = "rollerauction"
    SITE_NAME = "Roller Auction"

    def login(self, page) -> bool:
        """
        TODO: Inspect the login page and update selectors below.

        Note: Roller Auction is a smaller regional site. Check if their login
        is a standard HubSpot form or a custom page. Look for the email and
        password fields in the page source.
        """
        try:
            page.goto(LOGIN_URL, wait_until="networkidle")

            # TODO: Replace with actual selectors
            page.fill('input[type="email"]', self.email)       # TODO: verify
            page.fill('input[type="password"]', self.password) # TODO: verify
            page.click('button[type="submit"]')                # TODO: verify

            # TODO: Replace with a selector that only appears when logged in
            page.wait_for_selector(".user-account", timeout=10000)  # TODO
            return True
        except Exception as exc:
            logger.error("[%s] Login error: %s", self.SITE_NAME, exc)
            return False

    def search(self, page, term: str) -> list[AuctionItem]:
        """
        TODO: Inspect search results and update selectors below.

        Roller Auction is a smaller operation — they may list all items on a
        single "upcoming auctions" page rather than offering a search. In that
        case, navigate to their upcoming auctions page and filter by keyword
        client-side (or just return all items and let scraper.py filter by term).
        """
        items = []
        try:
            # TODO: Verify the correct search URL or upcoming auctions page
            search_url = f"{SEARCH_URL}?q={term.replace(' ', '+')}"
            page.goto(search_url, wait_until="networkidle")

            # TODO: Wait for results
            page.wait_for_selector(".auction-item", timeout=15000)   # TODO: real selector

            cards = page.query_selector_all(".auction-item")          # TODO: real selector
            for card in cards:
                # TODO: Extract fields
                title = card.query_selector(".item-title")            # TODO
                link  = card.query_selector("a")                      # TODO
                city  = card.query_selector(".item-location")         # TODO
                date  = card.query_selector(".item-date")             # TODO
                image = card.query_selector("img")                    # TODO

                if not title or not link:
                    continue

                href = link.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://rollerauction.com" + href

                item_id = href.split("/")[-1] or href   # TODO: make more robust

                items.append(AuctionItem(
                    site=self.SITE_ID,
                    item_id=item_id,
                    title=title.inner_text().strip() if title else "",
                    url=href,
                    location_city=city.inner_text().strip() if city else "",
                    auction_date=date.inner_text().strip() if date else None,
                    image_url=image.get_attribute("src") if image else "",
                ))

        except Exception as exc:
            logger.error("[%s] Search error for '%s': %s", self.SITE_NAME, term, exc)

        return items
