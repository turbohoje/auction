#!/usr/bin/env python3
"""
Auction Scraper — main entry point.

Usage:
    python scraper.py                   # normal run
    python scraper.py --dry-run         # print results, don't update cache/html
    python scraper.py --site rbauction  # run only one site
    python scraper.py --no-headless     # show browser windows (for debugging)
"""

import argparse
import json
import logging
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pgeocode
import yaml
from dotenv import load_dotenv
from jinja2 import Template
from playwright.sync_api import sync_playwright

from scrapers import SCRAPERS

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------
_geocoder = pgeocode.Nominatim("us")


def zip_to_latlon(zipcode: str):
    """Return (lat, lon) for a US zip code, or None if not found."""
    result = _geocoder.query_postal_code(zipcode)
    if result is None or math.isnan(result.latitude):
        return None
    return (result.latitude, result.longitude)


def haversine_miles(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in miles between two (lat, lon) points."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def item_in_region(item, region_lat, region_lon, radius_miles) -> bool:
    """
    Return True if the item's location is within radius_miles of the region center.

    Falls back to True (include) if the item has no zip code, so that items with
    missing location data are not silently dropped. Adjust this policy if you prefer
    to exclude unlocated items.
    """
    # Prefer zip, fall back to city/state
    # TODO: If items contain a zip code field, use it for better accuracy.
    #   Currently item.location_zip may be empty — scrapers should populate it.
    if item.location_zip:
        coords = zip_to_latlon(item.location_zip)
        if coords:
            dist = haversine_miles(region_lat, region_lon, *coords)
            return dist <= radius_miles

    # No usable location — include by default
    return True


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)
    return {}


def save_cache(cache_path: Path, cache: dict):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)


def merge_into_cache(cache: dict, new_items: list, expiry_days: int) -> tuple[list, list]:
    """
    Merge new_items into cache.

    Returns:
        (all_active_items, newly_added_uids)
        - all_active_items: full list of non-expired cache entries as dicts
        - newly_added_uids: UIDs that were not in cache before this run
    """
    today = datetime.utcnow().date()
    expiry_cutoff = today - timedelta(days=expiry_days)
    new_uids = []

    for item in new_items:
        uid = item.uid
        if uid not in cache:
            new_uids.append(uid)
            cache[uid] = {
                **item.to_dict(),
                "uid": uid,
                "first_seen": today.isoformat(),
                "last_seen": today.isoformat(),
                "is_new": True,
            }
        else:
            cache[uid]["last_seen"] = today.isoformat()
            cache[uid]["is_new"] = False
            # Update mutable fields that may change
            cache[uid]["auction_date"] = item.auction_date
            cache[uid]["price_estimate"] = item.price_estimate
            cache[uid]["matched_terms"] = list(
                set(cache[uid].get("matched_terms", []) + item.matched_terms)
            )

    # Expire old entries
    expired = [
        uid for uid, entry in cache.items()
        if entry.get("last_seen", "1970-01-01") < expiry_cutoff.isoformat()
    ]
    for uid in expired:
        logger.info("Expiring stale item: %s", cache[uid].get("title", uid))
        del cache[uid]

    return list(cache.values()), new_uids


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Auction Matches</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f4f4f4;
      color: #222;
      padding: 12px;
    }
    h1 { font-size: 1.3rem; margin-bottom: 4px; }
    .meta { font-size: 0.8rem; color: #666; margin-bottom: 16px; }
    .region-section { margin-bottom: 28px; }
    .region-title {
      font-size: 1.1rem;
      font-weight: 700;
      border-left: 4px solid #e67e22;
      padding-left: 8px;
      margin-bottom: 12px;
    }
    .item-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 12px;
    }
    .card {
      background: #fff;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 4px rgba(0,0,0,0.12);
      display: flex;
      flex-direction: column;
    }
    .card.is-new {
      border: 2px solid #27ae60;
    }
    .new-badge {
      background: #27ae60;
      color: #fff;
      font-size: 0.7rem;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 0 0 6px 0;
      align-self: flex-start;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .card img {
      width: 100%;
      height: 160px;
      object-fit: cover;
      background: #ddd;
    }
    .card-body { padding: 10px; flex: 1; display: flex; flex-direction: column; gap: 4px; }
    .card-title { font-size: 0.95rem; font-weight: 600; line-height: 1.3; }
    .card-meta { font-size: 0.78rem; color: #555; }
    .card-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
    .tag {
      font-size: 0.7rem;
      background: #eef2ff;
      color: #4050a0;
      border-radius: 4px;
      padding: 1px 6px;
    }
    .card-link {
      display: block;
      margin-top: 8px;
      padding: 6px;
      background: #2c3e50;
      color: #fff;
      text-align: center;
      border-radius: 5px;
      text-decoration: none;
      font-size: 0.85rem;
    }
    .no-results { color: #888; font-style: italic; padding: 8px 0; }
    @media (max-width: 400px) {
      .item-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <h1>Auction Matches</h1>
  <p class="meta">Updated: {{ updated_at }} &nbsp;|&nbsp; {{ total_items }} item(s) across {{ total_sites }} site(s)</p>

  {% for region in regions %}
  <section class="region-section">
    <div class="region-title">{{ region.name }} &mdash; {{ region.zip }} ({{ region.radius_miles }}mi radius)</div>

    {% if region.items %}
    <div class="item-grid">
      {% for item in region.items %}
      <div class="card {% if item.is_new %}is-new{% endif %}">
        {% if item.is_new %}<span class="new-badge">New</span>{% endif %}
        {% if item.image_url %}
        <img src="{{ item.image_url }}" alt="{{ item.title }}" loading="lazy">
        {% endif %}
        <div class="card-body">
          <div class="card-title">{{ item.title }}</div>
          <div class="card-meta">
            {% if item.location_city %}📍 {{ item.location_city }}{% if item.location_state %}, {{ item.location_state }}{% endif %}{% endif %}
            {% if item.auction_date %}<br>🗓 {{ item.auction_date }}{% endif %}
            {% if item.price_estimate %}<br>💲 {{ item.price_estimate }}{% endif %}
            <br>🏷 {{ item.site_name }}
            <br>👁 First seen: {{ item.first_seen }}
          </div>
          {% if item.matched_terms %}
          <div class="card-tags">
            {% for t in item.matched_terms %}<span class="tag">{{ t }}</span>{% endfor %}
          </div>
          {% endif %}
          <a class="card-link" href="{{ item.url }}" target="_blank" rel="noopener">View Listing ↗</a>
        </div>
      </div>
      {% endfor %}
    </div>
    {% else %}
    <p class="no-results">No matches found for this region.</p>
    {% endif %}
  </section>
  {% endfor %}
</body>
</html>
"""

SITE_DISPLAY_NAMES = {
    "rbauction":    "RB Auction",
    "rollerauction": "Roller Auction",
    "equipbid":     "Equip-Bid",
}


def build_html(regions_config: list, all_items: list) -> str:
    """Render the HTML output from cached items, grouped by region."""
    template = Template(HTML_TEMPLATE)

    region_sections = []
    for region in regions_config:
        lat_lon = zip_to_latlon(region["zip"])
        region_items = []

        for entry in all_items:
            item_zip = entry.get("location_zip", "")
            if lat_lon and item_zip:
                coords = zip_to_latlon(item_zip)
                if coords:
                    dist = haversine_miles(*lat_lon, *coords)
                    if dist > region["radius_miles"]:
                        continue

            # Check that at least one of this region's search terms matched
            matched = set(entry.get("matched_terms", []))
            region_terms = set(region["search_terms"])
            if not matched.intersection(region_terms):
                continue

            region_items.append({
                **entry,
                "site_name": SITE_DISPLAY_NAMES.get(entry.get("site", ""), entry.get("site", "")),
            })

        region_sections.append({
            "name": region["name"],
            "zip": region["zip"],
            "radius_miles": region["radius_miles"],
            "items": region_items,
        })

    total_items = sum(len(r["items"]) for r in region_sections)
    total_sites = len({i.get("site") for r in region_sections for i in r["items"]})

    return template.render(
        updated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        total_items=total_items,
        total_sites=total_sites,
        regions=region_sections,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_config(path="config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def get_credentials(site_id: str) -> dict:
    prefix = site_id.upper()
    return {
        "email":    os.getenv(f"{prefix}_EMAIL", ""),
        "password": os.getenv(f"{prefix}_PASSWORD", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="Auction scraper")
    parser.add_argument("--dry-run",    action="store_true", help="Don't write cache or HTML")
    parser.add_argument("--no-headless", action="store_true", help="Show browser windows")
    parser.add_argument("--site",        help="Run only this site ID (e.g. rbauction)")
    args = parser.parse_args()

    load_dotenv()
    config = load_config()

    if args.no_headless:
        config["browser"]["headless"] = False

    cache_path  = Path(config["output"]["cache_file"])
    output_path = Path(config["output"]["html_file"])
    expiry_days = config["output"].get("item_expiry_days", 30)

    # Build a flat list of (site_id, [search_terms]) pairs based on regions
    site_terms: dict[str, set] = {}
    for region in config["regions"]:
        for term in region["search_terms"]:
            for site in config["sites"]:
                if not site.get("enabled"):
                    continue
                sid = site["id"]
                if args.site and sid != args.site:
                    continue
                site_terms.setdefault(sid, set()).add(term)

    # Run scrapers
    all_new_items = []
    with sync_playwright() as pw:
        for site in config["sites"]:
            sid = site["id"]
            if not site.get("enabled"):
                continue
            if args.site and sid != args.site:
                continue
            if sid not in SCRAPERS:
                logger.warning("No scraper module for site '%s', skipping.", sid)
                continue
            terms = list(site_terms.get(sid, []))
            if not terms:
                continue

            creds   = get_credentials(sid)
            scraper = SCRAPERS[sid](creds, config["browser"])

            logger.info("=== %s | %d search term(s) ===", site["name"], len(terms))
            items = scraper.run(pw, terms)
            logger.info("=== %s | found %d item(s) ===", site["name"], len(items))
            all_new_items.extend(items)

    if args.dry_run:
        logger.info("[dry-run] Would have processed %d item(s). No files written.", len(all_new_items))
        for item in all_new_items:
            logger.info("  %s  %s", item.uid, item.title)
        return

    # Merge with cache
    cache = load_cache(cache_path)
    all_items, new_uids = merge_into_cache(cache, all_new_items, expiry_days)
    save_cache(cache_path, cache)
    logger.info("Cache: %d total | %d new this run", len(all_items), len(new_uids))

    # Write HTML
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = build_html(config["regions"], all_items)
    output_path.write_text(html)
    logger.info("HTML written to %s", output_path)

    if new_uids:
        logger.info("New items this run:")
        for uid in new_uids:
            entry = cache.get(uid, {})
            logger.info("  + %s  %s", uid, entry.get("title", ""))


if __name__ == "__main__":
    main()
