"""
Image and content-enrichment helpers used across the project.

1. text_placeholder_url() — generates a colored placeholder showing the restaurant's
   actual name via placehold.co. No network call needed to *generate* the URL, and
   it never looks like a wrong/misleading photo (a building, a wave, etc.) — it's
   honestly a placeholder, not a stand-in photo pretending to be real. Used for the
   instant, zero-setup synthetic seed data.

2. fetch_foodish_image() — pulls a REAL food photo from the free Foodish API
   (foodish-api.com, no key required), matched loosely to the restaurant's cuisine.

3. fetch_and_encode_google_photo() — downloads a Google Place photo ONCE at
   ingestion time, resizes/compresses it, and returns it as base64 — stored
   permanently in the database rather than re-fetched live from Google every time
   someone views the page. Fetching live on every view was the actual cause of
   both flaky/missing images (rate limits, transient failures showing as broken
   images) and slow page loads (a live Google round-trip per photo per view).

4. extract_popular_items() — pulls out commonly-mentioned dish names from a
   restaurant's review text, as a lightweight stand-in for "recommended items"
   since no real menu data source exists for free. Honest about what it is: what
   other reviewers mention most, not a menu.

5. estimate_cost_for_two() — a deterministic, clearly-labeled ESTIMATE (not real
   pricing data, which isn't available for free at this scale) based on cuisine
   type, city cost-of-living tier, and Google's priceLevel when available.
"""
import base64
import hashlib
import io
import urllib.parse
from collections import Counter

import requests
from PIL import Image

FOODISH_BASE = "https://foodish-api.com/api"

CUISINE_TO_FOODISH_CATEGORY = {
    "Biryani": "biryani",
    "Fast Food": "burger",
    "Italian": "pizza",
    "Cafe": "dessert",
}

PALETTE = ["e8734a", "3f7d58", "4a6fa5", "b5563c", "8a5a9e", "3f8f8f", "c2894f"]


def text_placeholder_url(name: str, width: int = 480, height: int = 320) -> str:
    """Deterministic colored placeholder with the restaurant's name on it —
    generated purely from the name, no network call required to build the URL."""
    color = PALETTE[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(PALETTE)]
    label = urllib.parse.quote(name[:28])
    return f"https://placehold.co/{width}x{height}/{color}/ffffff?text={label}&font=roboto"


def fetch_foodish_image(cuisines, timeout: float = 4.0):
    """Returns a real food photo URL from Foodish, loosely matched to cuisine.
    Returns None on any failure (timeout, service down, bad response) — callers
    should fall back to text_placeholder_url() when this returns None."""
    category = None
    for c in cuisines or []:
        if c in CUISINE_TO_FOODISH_CATEGORY:
            category = CUISINE_TO_FOODISH_CATEGORY[c]
            break

    url = f"{FOODISH_BASE}/images/{category}" if category else f"{FOODISH_BASE}/"

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        image_url = data.get("image")
        return image_url if image_url else None
    except Exception:
        return None


def fetch_and_encode_google_photo(photo_name: str, api_key: str, max_dimension: int = 800,
                                   timeout: float = 12.0):
    """Downloads a Google Place photo and returns it as a resized base64 JPEG string,
    or None on any failure. Meant to be called ONCE per photo at ingestion time —
    the result is stored in the database, never fetched live again at view time."""
    url = f"https://places.googleapis.com/v1/{photo_name}/media"
    params = {"maxWidthPx": max_dimension, "key": api_key}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        img.thumbnail((max_dimension, max_dimension))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


# Common dish/food-item keywords worth surfacing from review text. Deliberately
# a fixed vocabulary rather than generic noun extraction — far more precise for
# "what dish do people mention" than a general-purpose NLP noun-phrase extractor
# would be, and needs no extra model dependency.
FOOD_ITEM_VOCAB = [
    "biryani", "butter chicken", "paneer tikka", "paneer butter masala", "dosa",
    "idli", "idly", "vada", "samosa", "momos", "momo", "chowmein", "fried rice",
    "manchurian", "naan", "roti", "paratha", "tandoori chicken", "kebab", "kabab",
    "tikka masala", "dal makhani", "chole bhature", "pav bhaji", "vada pav",
    "pizza", "pasta", "burger", "fries", "sandwich", "shawarma", "sushi",
    "thali", "curry", "korma", "rogan josh", "seekh kebab", "gulab jamun",
    "kulfi", "lassi", "filter coffee", "masala chai", "cold coffee", "mocktail",
    "chicken 65", "prawns", "fish curry", "hyderabadi biryani", "haleem",
]


def extract_popular_items(review_texts, top_n: int = 5):
    """Counts mentions of known dish names across a restaurant's reviews and
    returns the most-mentioned ones. This is what reviewers talk about, not a
    real menu — the frontend labels it accordingly."""
    combined = " ".join(review_texts).lower()
    counts = Counter()
    for item in FOOD_ITEM_VOCAB:
        c = combined.count(item)
        if c > 0:
            counts[item.title()] += c
    return [item for item, _ in counts.most_common(top_n)]


# Rough cost-of-living tiers — used only to vary the estimate a bit by city,
# not a claim about real menu prices.
METRO_TIER_CITIES = {"Mumbai", "Delhi", "Bangalore", "Chennai", "Kolkata", "Hyderabad"}
BASE_COST_BY_CUISINE = {
    "Fast Food": 350, "Cafe": 450, "South Indian": 400, "North Indian": 550,
    "Biryani": 500, "Chinese": 500, "Continental": 900, "Italian": 850,
    "Multi-cuisine": 600,
}
PRICE_LEVEL_MULTIPLIER = {
    "PRICE_LEVEL_INEXPENSIVE": 0.7, "PRICE_LEVEL_MODERATE": 1.0,
    "PRICE_LEVEL_EXPENSIVE": 1.6, "PRICE_LEVEL_VERY_EXPENSIVE": 2.3,
}


def estimate_cost_for_two(name: str, cuisines, city: str, google_price_level=None) -> int:
    """A clearly-labeled ESTIMATE for two people, in rupees — deterministic per
    restaurant (same inputs always give the same number), not real pricing data."""
    base = max((BASE_COST_BY_CUISINE.get(c, 500) for c in (cuisines or [])), default=500)
    city_multiplier = 1.15 if city in METRO_TIER_CITIES else 0.9
    variation = 0.85 + (int(hashlib.md5(name.encode()).hexdigest(), 16) % 30) / 100  # 0.85-1.14

    price_multiplier = PRICE_LEVEL_MULTIPLIER.get(google_price_level, 1.0)

    estimate = base * city_multiplier * variation * price_multiplier
    return int(round(estimate / 50) * 50)  # round to nearest 50
