"""
Scraper for Ritchie Bros. Auction (rbauction.com).

TODO checklist before this scraper works:
  1. Confirm login flow selectors (see login() method)
  2. Confirm search URL structure and result selectors (see search() method)
  3. Inspect the network tab in DevTools to see if search results are loaded
     via XHR/fetch — if so, hitting the JSON endpoint directly may be easier
     than parsing the rendered page.
"""

import logging

from .base import AuctionItem, BaseScraper

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.rbauction.com/sign-in"
SEARCH_URL = "https://www.rbauction.com/equipment"  # TODO: verify


class RBAuctionScraper(BaseScraper):
    SITE_ID = "rbauction"
    SITE_NAME = "RB Auction"

    def login(self, page) -> bool:
        """
        TODO: Inspect the login page and update selectors below.

        Suggested steps:
          1. Open https://www.rbauction.com/sign-in in DevTools
          2. Identify the email input, password input, and submit button selectors
          3. Verify that after submit, a logged-in element appears (e.g. account menu)
        """
        try:
            page.goto(LOGIN_URL, wait_until="networkidle")

            # TODO: Replace with actual selectors from the login page
            page.fill('input[name="email"]', self.email)          # TODO: verify selector
            page.fill('input[name="password"]', self.password)    # TODO: verify selector
            page.click('button[type="submit"]')                    # TODO: verify selector

            # TODO: Replace with a selector that only appears when logged in
            page.wait_for_selector('[data-testid="user-menu"]', timeout=10000)  # TODO
            return True
        except Exception as exc:
            logger.error("[%s] Login error: %s", self.SITE_NAME, exc)
            return False

    def search(self, page, term: str) -> list[AuctionItem]:
        """
        TODO: Inspect the search/results page and update selectors below.

        Suggested approach:
          1. Perform a manual search at rbauction.com/equipment?q=<term>
          2. Open Network tab, filter by Fetch/XHR — look for a JSON API call
             returning listings. If found, replicate that request instead of
             parsing HTML.
          3. If no JSON API, identify the listing card selector, then extract
             title, URL, location, date, image from each card.

        Filters to apply (if available):
          - upcoming/active only (not sold/past)
          - optionally filter by location on the site itself to narrow results
            before the geo-filter in scraper.py does a radius check
        """
        items = []
        try:
            # TODO: Verify that appending ?q=<term> is the correct search URL pattern
            search_url = f"https://www.rbauction.com/equipment?q={term.replace(' ', '+')}"
            page.goto(search_url, wait_until="networkidle")

            # TODO: Wait for listing cards to appear
            page.wait_for_selector(".listing-card", timeout=15000)  # TODO: real selector

            cards = page.query_selector_all(".listing-card")         # TODO: real selector
            for card in cards:
                # TODO: Extract fields from each card using the right selectors
                title = card.query_selector(".listing-title")        # TODO
                link  = card.query_selector("a")                     # TODO
                city  = card.query_selector(".listing-location")     # TODO
                date  = card.query_selector(".listing-date")         # TODO
                image = card.query_selector("img")                   # TODO

                if not title or not link:
                    continue

                href = link.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.rbauction.com" + href

                # TODO: Parse item_id from href or a data attribute on the card
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
