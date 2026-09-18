"""Controlled real-data ingestion for the Food Review Platform.

This script deliberately does NOT run during FastAPI/Streamlit startup.
Use it when you want to refresh real restaurant data from Google Places.

Examples:
    python ingest_real.py --city Hyderabad
    python ingest_real.py --city Hyderabad --pages 2
    python ingest_real.py --city Mumbai --no-reviews
    python ingest_real.py --city Delhi --clear

Required environment variable:
    GOOGLE_PLACES_API_KEY

The Google Places API requires a billing-enabled Google Cloud project. Keep the
API key in a local .env file and never commit it.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
if not API_KEY:
    raise SystemExit(
        "GOOGLE_PLACES_API_KEY is not set. Add it to backend/.env or export it first."
    )

import places_ingest as places
from database import db

CITY_PRESETS = {
    "hyderabad": "Hyderabad",
    "bangalore": "Bangalore",
    "bengaluru": "Bangalore",
    "chennai": "Chennai",
    "mumbai": "Mumbai",
    "pune": "Pune",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "kolkata": "Kolkata",
    "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur",
    "visakhapatnam": "Visakhapatnam",
    "vizag": "Visakhapatnam",
}


def main():
    parser = argparse.ArgumentParser(description="Import real restaurant data from Google Places")
    parser.add_argument("--city", default="Hyderabad", help="One Indian city to ingest")
    parser.add_argument("--pages", type=int, default=1, choices=[1, 2],
                        help="Pages per search query; 1 is faster and cheaper")
    parser.add_argument("--clear", action="store_true",
                        help="Clear existing restaurants/reviews before importing")
    parser.add_argument("--no-reviews", action="store_true",
                        help="Do not request Google reviews; reduces API cost")
    parser.add_argument("--max-restaurants", type=int, default=60,
                        help="Safety cap for restaurants imported in this run")
    args = parser.parse_args()

    city = CITY_PRESETS.get(args.city.strip().lower(), args.city.strip())
    if not city:
        raise SystemExit("City cannot be empty.")

    # Keep ingestion small and explicit. This is the opposite of doing 30 cities
    # automatically whenever the API starts.
    places.API_KEY = API_KEY
    places.MAX_PAGES = args.pages
    places.QUERY_TEMPLATES = [
        "top rated restaurants in {city}, India",
        "budget restaurants in {city}, India",
        "cafes in {city}, India",
    ]

    if args.no_reviews:
        # Reviews are an Enterprise + Atmosphere field in Places API (New). For a
        # cheaper restaurant-catalog import, omit them from the field mask.
        places.FIELD_MASK = ",".join([
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.types",
            "places.photos",
            "places.googleMapsUri",
        ])

    if args.clear:
        confirm = input("This will delete all restaurants and reviews. Type DELETE to continue: ")
        if confirm != "DELETE":
            print("Cancelled.")
            return
        db.restaurants.delete_many({})
        db.reviews.delete_many({})

    existing_ids = {d.get("_id") for d in db.restaurants.find({}, {"_id": 1})}
    before = db.restaurants.count_documents({})

    print(f"\nImporting real Google Places data for: {city}")
    print(f"Existing restaurants: {before}")
    print(f"Pages/query: {args.pages} | Reviews: {'off' if args.no_reviews else 'on'}")
    print("This is a one-time data job; the web app will not wait for it at startup.\n")

    added = places.ingest_one_city(city, existing_ids)

    # Enforce the requested cap by removing the newest overflow entries from this
    # run only. In normal portfolio use, the default 60 is already conservative.
    if added > args.max_restaurants:
        docs = list(db.restaurants.find({"area": city}, {"_id": 1}).skip(args.max_restaurants))
        for doc in docs:
            rid = doc["_id"]
            db.reviews.delete_many({"restaurant_id": rid})
            db.restaurants.delete_one({"_id": rid})
        added = args.max_restaurants

    print(f"\nDone. Added approximately {added} real restaurants for {city}.")
    print(f"Total restaurants now: {db.restaurants.count_documents({})}")
    print(f"Total reviews now: {db.reviews.count_documents({})}")
    print("Start FastAPI/Streamlit normally now; startup will not perform ingestion.")


if __name__ == "__main__":
    main()
