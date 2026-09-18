import random
from datetime import datetime, timedelta

from database import db
from nlp import analyze_aspects, overall_sentiment
from placeholder_images import text_placeholder_url

random.seed(42)

CITIES = {
    # North
    "Delhi": (28.7041, 77.1025),
    "Jaipur": (26.9124, 75.7873),
    "Lucknow": (26.8467, 80.9462),
    "Kanpur": (26.4499, 80.3319),
    "Agra": (27.1767, 78.0081),
    "Chandigarh": (30.7333, 76.7794),
    "Ghaziabad": (28.6692, 77.4538),
    "Meerut": (28.9845, 77.7064),
    "Ludhiana": (30.9010, 75.8573),
    # West
    "Mumbai": (19.0760, 72.8777),
    "Pune": (18.5204, 73.8567),
    "Ahmedabad": (23.0225, 72.5714),
    "Surat": (21.1702, 72.8311),
    "Vadodara": (22.3072, 73.1812),
    "Nashik": (19.9975, 73.7898),
    "Rajkot": (22.3039, 70.8022),
    "Thane": (19.2183, 72.9781),
    # South
    "Hyderabad": (17.3850, 78.4867),
    "Bangalore": (12.9716, 77.5946),
    "Chennai": (13.0827, 80.2707),
    "Kochi": (9.9312, 76.2673),
    "Coimbatore": (11.0168, 76.9558),
    "Madurai": (9.9252, 78.1198),
    "Visakhapatnam": (17.6868, 83.2185),
    # East / Central / NE
    "Kolkata": (22.5726, 88.3639),
    "Patna": (25.5941, 85.1376),
    "Bhopal": (23.2599, 77.4126),
    "Indore": (22.7196, 75.8577),
    "Nagpur": (21.1458, 79.0882),
    "Guwahati": (26.1445, 91.7362),
    "Faridabad": (28.4089, 77.3178),
}

CUISINES = ["North Indian", "South Indian", "Chinese", "Italian",
            "Biryani", "Cafe", "Fast Food", "Continental"]

RESTAURANT_NAMES = [
    "Spice Route", "Paradise Biryani House", "Tandoor Nights", "Green Leaf Cafe",
    "Wok This Way", "Rustic Trattoria", "Chutneys", "The Curry Leaf", "Cafe Bahar",
    "Bawarchi Bites", "Momo Street", "Deccan Dine", "Charminar Grill", "Naan Stop",
    "Local House", "Pista House", "Southern Spice", "Roti Diaries", "Firangi Bake",
    "Ruchulu Kitchen", "Urban Tadka", "The Grand Thali", "Coastal Curry Co.",
    "Bombay Chowpatty", "Punjabi Rasoi", "Delhi Darbar", "South Blend",
]

RESTAURANTS_PER_CITY = 4

def fast_trust_scores(reviews):
    """Cheap deterministic trust heuristic for startup demo data.
    The full Isolation Forest remains enabled for real user submissions.
    """
    if not reviews:
        return []
    texts = [r.get("text", "").strip().lower() for r in reviews]
    scores = []
    for i, r in enumerate(reviews):
        duplicate = max((1.0 if texts[i] == texts[j] else 0.0 for j in range(len(texts)) if j != i), default=0.0)
        length = len(texts[i].split())
        length_score = min(1.0, length / 12.0)
        rating_score = 1.0 - abs((r.get("star_rating", 3) - 3) / 2.0) * 0.25
        score = max(0.05, min(1.0, 0.85 * length_score + 0.15 * rating_score - 0.65 * duplicate))
        scores.append(score)
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0] * len(scores)
    return [(x - lo) / (hi - lo) for x in scores]


GOOD_TEMPLATES = [
    "The {food} was absolutely delicious and full of flavor. {service} was quick "
    "and the {staff} were friendly. A bit {price} but worth it. The {ambience} was "
    "cozy and clean.",
    "Loved the {food} here, especially the biryani. {service} could be faster but "
    "the {staff} were polite. {price} for the quality. {ambience} felt hygienic "
    "and well maintained.",
    "Great {food}, generous portions. {service} was slow during peak hours. "
    "Reasonably {price}. {ambience} was a bit noisy but overall clean.",
]

BAD_TEMPLATES = [
    "The {food} was bland and cold when it arrived. {service} was rude and took "
    "forever. Way too {price} for what we got. The place felt {ambience}.",
    "Disappointing {food}, tasted stale. {staff} ignored us for 20 minutes. "
    "Overpriced. Also noticed the tables were not very clean.",
]


def gen_review_text(positive=True):
    template = random.choice(GOOD_TEMPLATES if positive else BAD_TEMPLATES)
    return template.format(
        food=random.choice(["biryani", "curry", "starters", "food", "dessert"]),
        service=random.choice(["Service", "The service"]),
        staff=random.choice(["waiters", "staff", "servers"]),
        price=random.choice(["pricey", "affordable", "reasonable", "expensive"]),
        ambience=random.choice(["dirty", "clean", "cozy", "noisy", "hygienic"]),
    )


def seed():
    db.restaurants.delete_many({})
    db.reviews.delete_many({})
    db.users.delete_many({})

    user_ids = [f"user_{i}" for i in range(1, 41)]
    for uid in user_ids:
        db.users.insert_one({
            "_id": uid,
            "name": uid.replace("_", " ").title(),
            "joined_at": datetime.utcnow() - timedelta(days=random.randint(10, 800)),
            "review_count": 0,
            "liked_restaurant_ids": [],
        })

    restaurant_docs = []
    rid_counter = 1
    for city, (base_lat, base_lng) in CITIES.items():
        names_for_city = random.sample(RESTAURANT_NAMES, k=RESTAURANTS_PER_CITY)
        for name in names_for_city:
            rid = f"rest_{rid_counter}"
            rid_counter += 1
            restaurant_docs.append({
                "_id": rid,
                "name": name,
                "area": city,
                "cuisine": random.sample(CUISINES, k=random.randint(1, 2)),
                "lat": base_lat + random.uniform(-0.08, 0.08),
                "lng": base_lng + random.uniform(-0.08, 0.08),
                # Deterministic placeholder image per restaurant (no API key needed).
                # Swap in real Google Places photos by setting GOOGLE_PLACES_API_KEY
                # and running places_ingest.py instead.
                # An honest text placeholder (restaurant's own name), not a random
                # unrelated stock photo — generated offline, no network dependency.
                # Swap in real photos by running osm_ingest.py or places_ingest.py.
                "image_url": text_placeholder_url(name),
                "created_at": datetime.utcnow() - timedelta(days=random.randint(100, 1000)),
            })
    db.restaurants.insert_many(restaurant_docs)

    for rest in restaurant_docs:
        rid = rest["_id"]
        n_reviews = random.randint(8, 15)
        review_docs = []

        for _ in range(n_reviews):
            is_positive = random.random() > 0.3
            text = gen_review_text(is_positive)
            rating = random.randint(4, 5) if is_positive else random.randint(1, 3)
            uid = random.choice(user_ids)
            review_docs.append({
                "restaurant_id": rid,
                "user_id": uid,
                "text": text,
                "star_rating": rating,
                "created_at": datetime.utcnow() - timedelta(days=random.randint(0, 400)),
            })

        # Plant a burst of near-duplicate fake reviews on ~half the restaurants
        # so the trust-scoring pipeline has real anomalies to catch.
        if random.random() > 0.5:
            fake_text = "Amazing amazing amazing best place ever!!! 5 stars!!!"
            for _ in range(random.randint(2, 3)):
                review_docs.append({
                    "restaurant_id": rid,
                    "user_id": random.choice(user_ids),
                    "text": fake_text,
                    "star_rating": 5,
                    "created_at": datetime.utcnow() - timedelta(hours=random.randint(0, 5)),
                })

        trust_scores = fast_trust_scores(review_docs)
        combined_text = []

        for idx, r in enumerate(review_docs):
            r["_id"] = f"{rid}_rev_{idx}"
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

        aspect_agg = {}
        score_map = {"positive": 5, "neutral": 3, "negative": 1}
        for aspect in ["food", "service", "price", "ambience", "hygiene"]:
            vals = [r["aspect_sentiment"][aspect] for r in review_docs if r["aspect_sentiment"][aspect]]
            aspect_agg[aspect] = round(sum(score_map[v] for v in vals) / len(vals), 2) if vals else 3.0

        db.restaurants.update_one({"_id": rid}, {"$set": {
            "avg_rating": round(avg_rating, 2),
            "trust_adjusted_rating": round(trust_adjusted, 2),
            "review_count": len(review_docs),
            "aspect_scores": aspect_agg,
            "combined_review_text": " ".join(combined_text),
        }})

    db.restaurants.create_index("area")
    db.restaurants.create_index("cuisine")

    print(f"Seeded {len(restaurant_docs)} restaurants with reviews "
          f"(including planted fake-review clusters for the trust demo).")


if __name__ == "__main__":
    seed()
