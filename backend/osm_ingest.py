"""
Fetches real restaurant listings (name, address, coordinates, cuisine tags) across
10 major Indian cities from OpenStreetMap — completely free, no API key, no billing
account, no signup of any kind. This is the option to use if you don't want to deal
with Google Cloud billing at all.

Trade-off vs places_ingest.py (Google): OSM does not carry photos or reviews, since
it's a map database, not a review platform. Restaurants ingested this way get the
same deterministic placeholder image already used for synthetic data, and start
with zero reviews — which is honestly how a real freshly-launched platform would
look anyway; reviews build up as real users start posting them.

How it works:
  1. Nominatim (OSM's free geocoder) resolves each city name to a bounding box.
  2. The Overpass API (OSM's free query engine) is queried for every node/way
     tagged amenity=restaurant inside that bounding box.
  3. Each result is loaded through the same finalize_restaurant() pipeline used
     by places_ingest.py, so behavior is identical to the Google-sourced path.

Both Nominatim and Overpass are shared public infrastructure with fair-use limits
(no official key, but they ask for a descriptive User-Agent and modest request
rates) — this script respects that with small delays between calls.

Run with:  python osm_ingest.py
"""
import time

import requests

from database import db
from places_ingest import finalize_restaurant
from placeholder_images import fetch_foodish_image, text_placeholder_url

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# A descriptive User-Agent is required by Nominatim's usage policy.
HEADERS = {"User-Agent": "food-review-platform-student-project/1.0"}

CITIES = [
    # North
    "Delhi", "Jaipur", "Lucknow", "Kanpur", "Agra", "Chandigarh",
    "Ghaziabad", "Meerut", "Ludhiana",
    # West
    "Mumbai", "Pune", "Ahmedabad", "Surat", "Vadodara", "Nashik",
    "Rajkot", "Thane",
    # South
    "Hyderabad", "Bangalore", "Chennai", "Kochi", "Coimbatore",
    "Madurai", "Visakhapatnam",
    # East / Central / NE
    "Kolkata", "Patna", "Bhopal", "Indore", "Nagpur", "Guwahati", "Faridabad",
]
RESULTS_PER_CITY = 8
# 30 cities against Overpass's free shared server, with the delays below, takes
# roughly 8-15 minutes end to end (longer if it gets rate-limited and has to back
# off) — this is a one-time ingestion run, not something you'll run often.

CUISINE_TAG_MAP = {
    "indian": "North Indian",
    "north_indian": "North Indian",
    "south_indian": "South Indian",
    "biryani": "Biryani",
    "chinese": "Chinese",
    "italian": "Italian",
    "pizza": "Italian",
    "cafe": "Cafe",
    "coffee_shop": "Cafe",
    "fast_food": "Fast Food",
    "burger": "Fast Food",
    "regional": "South Indian",
    "vegetarian": "South Indian",
    "continental": "Continental",
    "seafood": "Continental",
}


def guess_cuisines(cuisine_tag: str):
    """OSM's cuisine tag is a semicolon-separated free-text field, e.g. 'indian;chinese'."""
    if not cuisine_tag:
        return ["Multi-cuisine"]
    tags = [t.strip().lower() for t in cuisine_tag.split(";")]
    cuisines = list({CUISINE_TAG_MAP[t] for t in tags if t in CUISINE_TAG_MAP})
    return cuisines or ["Multi-cuisine"]


def get_city_bbox(city_name: str):
    """Returns (south, west, north, east) for a city via Nominatim, or None if not found."""
    params = {"q": f"{city_name}, India", "format": "json", "limit": 1}
    resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    # Nominatim returns boundingbox as [south, north, west, east] (strings)
    south, north, west, east = results[0]["boundingbox"]
    return float(south), float(west), float(north), float(east)


def query_restaurants(bbox, max_results, max_retries=4):
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:60];
    (
      node["amenity"="restaurant"]({south},{west},{north},{east});
      way["amenity"="restaurant"]({south},{west},{north},{east});
    );
    out center tags {max_results};
    """
    delay = 20  # Overpass's free shared server rate-limits aggressively — start generous
    for attempt in range(1, max_retries + 1):
        resp = requests.post(OVERPASS_URL, data={"data": query}, headers=HEADERS, timeout=90)
        if resp.status_code == 429:
            if attempt == max_retries:
                resp.raise_for_status()
            print(f"    Rate-limited by Overpass — waiting {delay}s before retry "
                  f"({attempt}/{max_retries})...")
            time.sleep(delay)
            delay *= 2  # back off further each retry
            continue
        resp.raise_for_status()
        return resp.json().get("elements", [])
    return []


def build_address(tags: dict) -> str:
    parts = [
        tags.get("addr:housenumber"),
        tags.get("addr:street"),
        tags.get("addr:suburb"),
        tags.get("addr:city"),
    ]
    return ", ".join(p for p in parts if p) or None


def ingest():
    # Only wipe restaurants/reviews — real user accounts (db.users) are left intact.
    db.restaurants.delete_many({})
    db.reviews.delete_many({})

    inserted = 0
    seen_ids = set()

    for city in CITIES:
        print(f"Resolving {city}...")
        try:
            bbox = get_city_bbox(city)
        except requests.RequestException as e:
            print(f"  Could not geocode '{city}': {e}")
            continue

        if not bbox:
            print(f"  No location found for '{city}', skipping.")
            continue

        time.sleep(1)  # Nominatim asks for max ~1 request/second

        print(f"  Querying restaurants in {city}...")
        try:
            elements = query_restaurants(bbox, RESULTS_PER_CITY)
        except requests.RequestException as e:
            print(f"  Overpass query failed for '{city}': {e}")
            continue

        count_for_city = 0
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name")
            if not name:
                continue  # skip unnamed nodes — not useful for a review platform

            pid = f"osm_{el['type']}_{el['id']}"
            if pid in seen_ids:
                # Adjacent cities' bounding boxes can overlap (e.g. Mumbai/Thane) —
                # the same physical restaurant can show up in both queries.
                continue
            seen_ids.add(pid)

            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lng = el.get("lon") or (el.get("center") or {}).get("lon")
            cuisine = guess_cuisines(tags.get("cuisine"))

            # OSM has no photos of its own — try a real food photo from Foodish
            # (free, no key), matched loosely to cuisine; fall back to an honest
            # text placeholder rather than a random unrelated stock photo.
            image_url = fetch_foodish_image(cuisine) or text_placeholder_url(name)

            doc = {
                "_id": pid,
                "name": name,
                "area": city,
                "cuisine": cuisine,
                "lat": lat,
                "lng": lng,
                "address": build_address(tags),
                "photo_name": None,
                "image_url": image_url,
            }
            try:
                db.restaurants.insert_one(doc)
            except Exception as e:
                print(f"    Skipped a duplicate/invalid entry: {e}")
                continue
            finalize_restaurant(pid, [])  # no reviews from OSM — starts at zero, like a fresh listing
            inserted += 1
            count_for_city += 1

        print(f"  Added {count_for_city} restaurants in {city}.")
        time.sleep(8)  # be gentle on the shared Overpass endpoint — its free tier rate-limits fast

    db.restaurants.create_index("area")
    db.restaurants.create_index("cuisine")

    print(f"\nIngested {inserted} real restaurants from OpenStreetMap across India — "
          f"completely free, no API key or billing required.")


if __name__ == "__main__":
    ingest()
