"""
Fetches real restaurant data (name, address, location, a real photo when Google has
one, and real Google reviews) across 30+ Indian cities using Places API (New), with
pagination and multiple search angles per city (top-rated, budget, cafes).

A real photo is downloaded for EVERY restaurant Google actually has one for — not
just a top-rated subset. Speed comes from parallelism (PHOTO_DOWNLOAD_WORKERS, default
15 concurrent downloads), not from limiting how many restaurants get a real photo.
Downloading photos one at a time sequentially for 80-90 restaurants in a city is what
made an earlier version of this script take ~10 minutes per city; downloading them
concurrently instead cuts that dramatically without sacrificing real-photo coverage.
A restaurant only falls back to a Foodish/placeholder image if Google genuinely has
no photo listed for it at all.

Setup required before running this:
  1. Google Cloud Console -> create/select a project -> enable billing
     (Places API (New) requires a billing account, but Google gives a recurring
     free monthly credit that comfortably covers a portfolio-scale project).
  2. APIs & Services -> Enable "Places API (New)" (search for it by that exact name
     - the old "Places API" listing is Legacy and can no longer be enabled on new
     projects).
  3. APIs & Services -> Credentials -> Create API key. Restrict it to "Places API (New)".
  4. Copy .env.example to .env and set GOOGLE_PLACES_API_KEY=<your key>.

Run with:  python places_ingest.py
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

from database import db
from nlp import analyze_aspects, overall_sentiment
from trust import compute_trust_scores
from placeholder_images import fetch_foodish_image, text_placeholder_url, fetch_and_encode_google_photo

load_dotenv()

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
PHOTO_DOWNLOAD_WORKERS = 15  # parallel downloads — I/O-bound, so more threads = much faster

# Restaurants are pulled from across India, not just Hyderabad. The "area" field
# in each restaurant document holds the city name, and the existing /areas filter
# in the frontend doubles as a city filter.
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
RESULTS_PER_PAGE = 20  # Places API (New) Text Search max results per page
MAX_PAGES = 2  # 2 pages (~40 results) per query is a good coverage/speed tradeoff

# 3 differentiated search angles instead of 5 — "popular" heavily overlapped with
# "top rated" in practice (same ranking signal), and "biryani" mostly duplicated
# restaurants "top rated" already found. These three cover distinctly different
# ground: general quality, budget-tier places top-rated queries tend to skip, and
# a different venue category entirely.
QUERY_TEMPLATES = [
    "top rated restaurants in {city}, India",
    "budget restaurants in {city}, India",
    "cafes in {city}, India",
]

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.types",
    "places.photos",
    "places.googleMapsUri",
    "places.reviews",
    "places.priceLevel",
])

CUISINE_TYPE_MAP = {
    "indian_restaurant": "North Indian",
    "south_indian_restaurant": "South Indian",
    "north_indian_restaurant": "North Indian",
    "chinese_restaurant": "Chinese",
    "italian_restaurant": "Italian",
    "cafe": "Cafe",
    "coffee_shop": "Cafe",
    "fast_food_restaurant": "Fast Food",
    "pizza_restaurant": "Italian",
    "seafood_restaurant": "Continental",
    "vegetarian_restaurant": "South Indian",
}


def guess_cuisines(types):
    cuisines = list({CUISINE_TYPE_MAP[t] for t in types if t in CUISINE_TYPE_MAP})
    return cuisines or ["Multi-cuisine"]


def text_search(query, max_pages=MAX_PAGES, max_retries=3):
    """Fetches up to max_pages * 20 results for a query, following Google's
    nextPageToken for pagination (their documented way to get more than 20
    results per search).

    Retries transient network failures (timeouts, SSL handshake issues,
    connection resets) with backoff — these happen on real networks and
    shouldn't kill an hours-long ingestion run over one flaky request."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    all_places = []
    page_token = None

    for page in range(max_pages):
        body = {"textQuery": query, "maxResultCount": RESULTS_PER_PAGE}
        if page_token:
            body["pageToken"] = page_token

        data = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=20)
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.exceptions.RequestException as e:
                if attempt == max_retries:
                    raise
                wait = 3 * attempt
                print(f"    Network hiccup on '{query}' (attempt {attempt}/{max_retries}: "
                      f"{type(e).__name__}) — retrying in {wait}s...")
                time.sleep(wait)

        places = data.get("places", [])
        all_places.extend(places)

        page_token = data.get("nextPageToken")
        if not page_token or not places:
            break
        time.sleep(2)  # a fresh pageToken needs a moment before Google will accept it

    return all_places


def build_review_docs(place):
    """Convert Google's review objects into our internal review format."""
    docs = []
    for rev in place.get("reviews", []) or []:
        text = (rev.get("text") or {}).get("text", "").strip()
        if not text:
            continue
        docs.append({
            "user_id": "google_" + (rev.get("authorAttribution", {}).get("displayName", "reviewer")
                                     .lower().replace(" ", "_")),
            "text": text,
            "star_rating": int(rev.get("rating", 3)),
            "created_at": rev.get("publishTime"),
            "source": "google",
        })
    return docs


def finalize_restaurant(restaurant_id, review_docs):
    """Score reviews (aspect sentiment + trust) and write aggregate fields — same
    pipeline used for user-submitted reviews, so real and synthetic data behave
    identically once ingested."""
    if not review_docs:
        db.restaurants.update_one({"_id": restaurant_id}, {"$set": {
            "avg_rating": None,
            "trust_adjusted_rating": None,
            "review_count": 0,
            "aspect_scores": {a: 0 for a in ["food", "service", "price", "ambience", "hygiene"]},
            "combined_review_text": "",
        }})
        return

    trust_scores = compute_trust_scores(review_docs)
    combined_text = []

    for idx, r in enumerate(review_docs):
        r["_id"] = f"{restaurant_id}_rev_{idx}"
        r["restaurant_id"] = restaurant_id
        r["aspect_sentiment"] = analyze_aspects(r["text"])
        r["overall_sentiment"] = overall_sentiment(r["text"])
        r["trust_score"] = round(trust_scores[idx], 3)
        r["trust_flag"] = "verified" if trust_scores[idx] > 0.4 else "flagged"
        combined_text.append(r["text"])
        db.reviews.insert_one(r)

    avg_rating = sum(r["star_rating"] for r in review_docs) / len(review_docs)
    total_trust = sum(r["trust_score"] for r in review_docs)
    trust_adjusted = (
        sum(r["star_rating"] * r["trust_score"] for r in review_docs) / total_trust
        if total_trust else avg_rating
    )

    score_map = {"positive": 5, "neutral": 3, "negative": 1}
    aspect_agg = {}
    for aspect in ["food", "service", "price", "ambience", "hygiene"]:
        vals = [r["aspect_sentiment"][aspect] for r in review_docs if r["aspect_sentiment"][aspect]]
        aspect_agg[aspect] = round(sum(score_map[v] for v in vals) / len(vals), 2) if vals else 3.0

    db.restaurants.update_one({"_id": restaurant_id}, {"$set": {
        "avg_rating": round(avg_rating, 2),
        "trust_adjusted_rating": round(trust_adjusted, 2),
        "review_count": len(review_docs),
        "aspect_scores": aspect_agg,
        "combined_review_text": " ".join(combined_text),
    }})


def ingest():
    if not API_KEY:
        raise SystemExit(
            "GOOGLE_PLACES_API_KEY is not set. Copy .env.example to .env, add your key, "
            "and see the setup steps in this file's docstring."
        )

    # Only wipe restaurants/reviews — real user accounts (db.users) are left intact.
    db.restaurants.delete_many({})
    db.reviews.delete_many({})

    seen_ids = set()
    inserted = 0

    for city in CITIES:
        print(f"\n{city}:")
        try:
            inserted += ingest_one_city(city, seen_ids)
        except Exception as e:
            # Last-resort safety net: an unexpected failure anywhere in this
            # city's processing (a DB hiccup, a malformed response, etc.) skips
            # just this city instead of losing every other city already done —
            # this is exactly the kind of crash that previously killed an
            # hours-long run over one bad city.
            print(f"  !! Unexpected error processing {city}, skipping it and "
                  f"continuing — {type(e).__name__}: {e}")
            continue

    db.restaurants.create_index("area")
    db.restaurants.create_index("cuisine")

    print(f"\nIngested {inserted} real restaurants from across India via Google Places, "
          f"with real reviews run through the aspect-sentiment and trust-scoring pipeline.")


def ingest_one_city(city, seen_ids):
    """Searches, downloads photos for, and inserts all restaurants found for one
    city. Returns the number of restaurants added. Network-level failures on
    individual search queries are already handled with retries inside
    text_search(); this function additionally propagates anything unexpected
    so the caller's try/except can skip just this city rather than crashing."""
    city_places = []  # (place_dict) collected across all query templates first

    for template in QUERY_TEMPLATES:
        query = template.format(city=city)
        print(f"  Searching: {query}")
        try:
            places = text_search(query)
        except requests.exceptions.RequestException as e:
            print(f"    Skipped this query after retries — {type(e).__name__}: {e}")
            continue

        for p in places:
            pid = p.get("id")
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            city_places.append(p)

        time.sleep(0.4)  # be gentle on the API between queries

    if not city_places:
        print(f"  -> 0 restaurants found for {city}")
        return 0

    # Download a real photo for EVERY restaurant that actually has one available
    # from Google — not just a top-rated subset. An earlier version of this
    # script capped this to the top 20 by rating, which meant plenty of real
    # restaurants with a perfectly good Google photo available got a colored
    # text placeholder instead, just because they weren't in the top 20. High
    # parallelism (not an artificial cap) is what keeps this fast: downloads
    # are independent, I/O-bound network calls, so throwing more workers at
    # them scales well even for 80-90 restaurants in one city.
    photo_refs_by_id = {}
    for p in city_places:
        refs = [ph.get("name") for ph in (p.get("photos") or [])[:1] if ph.get("name")]
        if refs:
            photo_refs_by_id[p["id"]] = refs[0]

    print(f"  Downloading {len(photo_refs_by_id)} real photos out of "
          f"{len(city_places)} restaurants found ({PHOTO_DOWNLOAD_WORKERS} at a time)...")
    images_by_id = {}
    if photo_refs_by_id:
        with ThreadPoolExecutor(max_workers=PHOTO_DOWNLOAD_WORKERS) as pool:
            future_to_id = {
                pool.submit(fetch_and_encode_google_photo, ref, API_KEY): pid
                for pid, ref in photo_refs_by_id.items()
            }
            for future in as_completed(future_to_id):
                pid = future_to_id[future]
                try:
                    encoded = future.result()
                    if encoded:
                        images_by_id[pid] = [encoded]
                except Exception:
                    pass  # this one restaurant just falls back to Foodish/placeholder below

    city_count = 0
    for p in city_places:
        pid = p["id"]
        name = p.get("displayName", {}).get("text", "Unknown")
        cuisine = guess_cuisines(p.get("types", []))
        images = images_by_id.get(pid, [])

        image_url = None
        if not images:
            # No usable Google photo — try a real food photo from Foodish
            # (free, no key), falling back to a text placeholder.
            image_url = fetch_foodish_image(cuisine) or text_placeholder_url(name)

        doc = {
            "_id": pid,
            "name": name,
            "area": city,
            "cuisine": cuisine,
            "lat": (p.get("location") or {}).get("latitude"),
            "lng": (p.get("location") or {}).get("longitude"),
            "address": p.get("formattedAddress"),
            "google_rating": p.get("rating"),
            "google_rating_count": p.get("userRatingCount"),
            "google_price_level": p.get("priceLevel"),
            "images": images,       # permanently stored, resized base64 photos
            "image_url": image_url,  # only set as a fallback when images is empty
            "data_source": "Google Places",
            "google_maps_uri": p.get("googleMapsUri"),
        }
        db.restaurants.insert_one(doc)

        review_docs = build_review_docs(p)
        finalize_restaurant(pid, review_docs)
        city_count += 1

    print(f"  -> {city_count} unique restaurants added for {city}")
    return city_count


if __name__ == "__main__":
    ingest()
