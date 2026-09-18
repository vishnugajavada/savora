import base64
import os
import re
import uuid
from datetime import datetime
from io import BytesIO
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query, Header, Depends, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field

from database import db
from nlp import analyze_aspects, overall_sentiment
from trust import compute_trust_scores
from recommend import recommend_for_user, recommend_similar, invalidate_cache
from auth import hash_password, verify_password, create_token, decode_token
from placeholder_images import extract_popular_items, estimate_cost_for_two

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_RE = re.compile(r'^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>_\-+=~`\[\];\'/\\]).{8,}$')
MAX_REVIEW_IMAGES = 4
MAX_IMAGE_DIMENSION = 900

app = FastAPI(title="India Food Review Intelligence Platform", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    phone: Optional[str] = None
    location: Optional[str] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class ContactMessage(BaseModel):
    name: str
    email: str
    subject: str
    message: str


def _rating(doc: dict) -> float:
    for key in ("trust_adjusted_rating", "avg_rating", "google_rating"):
        value = doc.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def serialize(doc: dict) -> dict:
    out = dict(doc)
    out.pop("password_hash", None)
    out.pop("combined_review_text", None)
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    if isinstance(out.get("joined_at"), datetime):
        out["joined_at"] = out["joined_at"].isoformat()
    if "cuisine" in out:
        out["cost_for_two"] = estimate_cost_for_two(
            out.get("name", ""), out.get("cuisine"), out.get("area", ""), out.get("google_price_level")
        )
        out["display_rating"] = round(_rating(out), 2)
    return out


_thumbnail_cache = {}


def get_list_thumbnail(doc: dict):
    rid = doc.get("_id")
    images = doc.get("images") or []
    if rid in _thumbnail_cache:
        return _thumbnail_cache[rid]
    if images:
        try:
            raw = base64.b64decode(images[0])
            img = Image.open(BytesIO(raw)).convert("RGB")
            img.thumbnail((220, 160))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=62)
            thumb = base64.b64encode(buf.getvalue()).decode("ascii")
            _thumbnail_cache[rid] = thumb
            return thumb
        except Exception:
            pass
    return doc.get("image_url")


def serialize_for_list(doc: dict) -> dict:
    out = serialize(doc)
    out["thumbnail"] = get_list_thumbnail(doc)
    out["has_photos"] = bool(doc.get("images") or doc.get("image_url") or doc.get("thumbnail"))
    out.pop("images", None)
    return out


def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in")
    user_id = decode_token(authorization.split(" ", 1)[1])
    if not user_id:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    return user_id


@app.on_event("startup")
def startup_seed_if_empty():
    if db.restaurants.count_documents({}) == 0:
        from seed_data import seed
        print("[startup] Database is empty — loading demo data.")
        seed()


@app.get("/")
def root():
    return {"status": "ok", "service": "India Food Review Intelligence Platform", "version": "2.0.0"}


@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "healthy", "database": "connected", "restaurants": db.restaurants.count_documents({})}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.post("/auth/signup")
def signup(req: SignupRequest):
    if not req.name.strip() or not EMAIL_RE.match(req.email.strip().lower()):
        raise HTTPException(status_code=400, detail="Enter a valid name and email")
    if not PASSWORD_RE.match(req.password):
        raise HTTPException(status_code=400, detail="Password needs 8+ chars, uppercase, number and special character")
    email = req.email.strip().lower()
    if db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with that email already exists")
    user_id = f"user_{uuid.uuid4().hex[:10]}"
    db.users.insert_one({
        "_id": user_id, "name": req.name.strip(), "email": email,
        "password_hash": hash_password(req.password), "joined_at": datetime.utcnow(),
        "review_count": 0, "liked_restaurant_ids": [], "phone": "", "location": "",
    })
    return {"token": create_token(user_id), "user_id": user_id, "name": req.name.strip()}


@app.post("/auth/login")
def login(req: LoginRequest):
    user = db.users.find_one({"email": req.email.strip().lower()})
    if not user or not verify_password(req.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return {"token": create_token(user["_id"]), "user_id": user["_id"], "name": user.get("name", "User")}


@app.get("/areas")
def get_areas():
    return sorted([x for x in db.restaurants.distinct("area") if x])


@app.get("/cities")
def get_cities():
    return get_areas()


@app.get("/cuisines")
def get_cuisines():
    values = [x for x in db.restaurants.distinct("cuisine") if x]
    return sorted(set(values), key=str.lower)


@app.get("/restaurants")
def get_restaurants(
    area: Optional[str] = None,
    city: Optional[str] = None,  # backwards-compatible alias
    cuisine: Optional[List[str]] = Query(None),
    min_rating: float = Query(1.0, ge=1.0, le=5.0),
    min_reviews: int = Query(0, ge=0),
    search: Optional[str] = None,
    sort: str = "rating",
):
    selected_area = (area or city or "").strip()
    query = {}
    if selected_area and selected_area.lower() != "all":
        # Existing real dataset uses `area`; city is accepted by the API but
        # never required by the frontend.
        query["area"] = selected_area
    if cuisine:
        query["cuisine"] = {"$in": cuisine}
    if min_reviews:
        query["review_count"] = {"$gte": min_reviews}
    if min_rating > 1.0:
        # Real ingested records may have only google_rating, only avg_rating,
        # or both. Filtering in Python keeps the endpoint compatible with all
        # versions of the dataset.
        query = {k: v for k, v in query.items() if k != "avg_rating"}

    results = list(db.restaurants.find(query))
    if min_rating > 1.0:
        results = [r for r in results if _rating(r) >= min_rating]
    if search and search.strip():
        needle = search.strip().lower()
        results = [r for r in results if needle in str(r.get("name", "")).lower()]

    if sort in ("rating", "trust"):
        results.sort(key=lambda r: _rating(r), reverse=True)
    elif sort == "reviews":
        results.sort(key=lambda r: int(r.get("review_count", 0) or 0), reverse=True)
    elif sort == "name":
        results.sort(key=lambda r: str(r.get("name", "")).lower())

    return [serialize_for_list(r) for r in results]


@app.get("/restaurants/{restaurant_id}")
def get_restaurant(restaurant_id: str):
    rest = db.restaurants.find_one({"_id": restaurant_id})
    if not rest:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return serialize(rest)


@app.get("/restaurants/{restaurant_id}/reviews")
def get_reviews(restaurant_id: str, verified_only: bool = False):
    query = {"restaurant_id": restaurant_id}
    if verified_only:
        query["trust_flag"] = "verified"
    reviews = list(db.reviews.find(query).sort("created_at", -1))
    return [serialize(r) for r in reviews]


@app.get("/restaurants/{restaurant_id}/popular-items")
def get_popular_items(restaurant_id: str):
    reviews = list(db.reviews.find({"restaurant_id": restaurant_id}, {"text": 1}))
    return {"items": extract_popular_items([r.get("text", "") for r in reviews if r.get("text")])}


@app.get("/restaurants/{restaurant_id}/similar")
def get_similar(restaurant_id: str, limit: int = Query(4, ge=1, le=12)):
    all_restaurants = list(db.restaurants.find({}))
    ids = recommend_similar(restaurant_id, all_restaurants, top_n=limit)
    return [serialize_for_list(r) for r in all_restaurants if r.get("_id") in ids]


def process_uploaded_image(raw_bytes: bytes) -> Optional[str]:
    try:
        img = Image.open(BytesIO(raw_bytes)).convert("RGB")
        img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=78)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


@app.post("/reviews")
async def create_review(
    restaurant_id: str = Form(...), text: str = Form(...), star_rating: int = Form(...),
    images: List[UploadFile] = File(default=[]), current_user: str = Depends(get_current_user),
):
    rest = db.restaurants.find_one({"_id": restaurant_id})
    if not rest:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Review text is required")
    if not 1 <= star_rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    user = db.users.find_one({"_id": current_user})
    user_name = user.get("name", "Anonymous") if user else "Anonymous"
    image_data = []
    for upload in images[:MAX_REVIEW_IMAGES]:
        raw = await upload.read()
        encoded = process_uploaded_image(raw) if raw else None
        if encoded:
            image_data.append(encoded)

    doc = {
        "_id": f"{restaurant_id}_rev_{uuid.uuid4().hex[:8]}",
        "restaurant_id": restaurant_id, "user_id": current_user, "user_name": user_name,
        "text": text.strip(), "star_rating": star_rating, "images": image_data,
        "created_at": datetime.utcnow(), "aspect_sentiment": analyze_aspects(text),
        "overall_sentiment": overall_sentiment(text),
    }
    existing = list(db.reviews.find({"restaurant_id": restaurant_id}))
    all_reviews = existing + [doc]
    scores = compute_trust_scores(all_reviews)
    doc["trust_score"] = round(scores[-1], 3)
    doc["trust_flag"] = "verified" if scores[-1] >= 0.4 else "flagged"
    db.reviews.insert_one(doc)

    recompute_restaurant_rating(restaurant_id)
    if user:
        db.users.update_one({"_id": current_user}, {"$inc": {"review_count": 1}})
    invalidate_cache()
    return serialize(doc)


def recompute_restaurant_rating(restaurant_id: str):
    """Shared by create/edit/delete review — keeps a restaurant's aggregate
    rating and review_count consistent with whatever reviews currently exist."""
    all_reviews = list(db.reviews.find({"restaurant_id": restaurant_id}))
    if not all_reviews:
        db.restaurants.update_one({"_id": restaurant_id}, {"$set": {
            "avg_rating": None, "trust_adjusted_rating": None, "review_count": 0,
        }})
        return
    avg = sum(r.get("star_rating", 0) for r in all_reviews) / len(all_reviews)
    weighted = sum(r.get("star_rating", 0) * r.get("trust_score", 1.0) for r in all_reviews)
    trust_sum = sum(r.get("trust_score", 1.0) for r in all_reviews)
    trust_rating = weighted / trust_sum if trust_sum else avg
    db.restaurants.update_one({"_id": restaurant_id}, {"$set": {
        "avg_rating": round(avg, 2), "trust_adjusted_rating": round(trust_rating, 2),
        "review_count": len(all_reviews),
    }})


class ReviewUpdate(BaseModel):
    text: str
    star_rating: int


@app.patch("/reviews/{review_id}")
def update_review(review_id: str, update: ReviewUpdate, current_user: str = Depends(get_current_user)):
    review = db.reviews.find_one({"_id": review_id})
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.get("user_id") != current_user:
        raise HTTPException(status_code=403, detail="You can only edit your own reviews")
    if not update.text.strip():
        raise HTTPException(status_code=400, detail="Review text is required")
    if not 1 <= update.star_rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    # Re-score trust across the restaurant's reviews with the edited text in place,
    # so an edit can't be used to dodge fake-review detection by slipping past it.
    updated_fields = {
        "text": update.text.strip(),
        "star_rating": update.star_rating,
        "aspect_sentiment": analyze_aspects(update.text),
        "overall_sentiment": overall_sentiment(update.text),
        "edited_at": datetime.utcnow(),
    }
    db.reviews.update_one({"_id": review_id}, {"$set": updated_fields})

    all_reviews = list(db.reviews.find({"restaurant_id": review["restaurant_id"]}))
    scores = compute_trust_scores(all_reviews)
    ids = [r["_id"] for r in all_reviews]
    idx = ids.index(review_id)
    db.reviews.update_one({"_id": review_id}, {"$set": {
        "trust_score": round(scores[idx], 3),
        "trust_flag": "verified" if scores[idx] >= 0.4 else "flagged",
    }})

    recompute_restaurant_rating(review["restaurant_id"])
    invalidate_cache()
    return serialize(db.reviews.find_one({"_id": review_id}))


@app.delete("/reviews/{review_id}")
def delete_review(review_id: str, current_user: str = Depends(get_current_user)):
    review = db.reviews.find_one({"_id": review_id})
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.get("user_id") != current_user:
        raise HTTPException(status_code=403, detail="You can only delete your own reviews")

    db.reviews.delete_one({"_id": review_id})
    recompute_restaurant_rating(review["restaurant_id"])
    if db.users.find_one({"_id": current_user}):
        db.users.update_one({"_id": current_user}, {"$inc": {"review_count": -1}})
    invalidate_cache()
    return {"status": "ok"}


@app.post("/reviews/{review_id}/report")
def report_review(review_id: str, current_user: str = Depends(get_current_user)):
    review = db.reviews.find_one({"_id": review_id})
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    db.reviews.update_one({"_id": review_id}, {
        "$addToSet": {"reported_by": current_user},
        "$set": {"last_reported_at": datetime.utcnow()},
    })
    report_count = len(db.reviews.find_one({"_id": review_id}).get("reported_by", []))
    return {"status": "ok", "report_count": report_count}


@app.post("/reviews/{review_id}/helpful")
def toggle_helpful(review_id: str, current_user: str = Depends(get_current_user)):
    """Toggle: voting again removes your vote, matching how 'helpful' buttons
    on most review platforms behave."""
    review = db.reviews.find_one({"_id": review_id})
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    already_voted = current_user in (review.get("helpful_by") or [])
    if already_voted:
        db.reviews.update_one({"_id": review_id}, {"$pull": {"helpful_by": current_user}})
    else:
        db.reviews.update_one({"_id": review_id}, {"$addToSet": {"helpful_by": current_user}})

    helpful_count = len(db.reviews.find_one({"_id": review_id}).get("helpful_by", []))
    return {"status": "ok", "helpful_count": helpful_count, "voted": not already_voted}


@app.get("/reviews/reported")
def get_reported_reviews(min_reports: int = Query(1, ge=1)):
    """Reviews the community has flagged, most-reported first — surfaces exactly
    the kind of content the trust-scoring system is meant to help catch."""
    reviews = list(db.reviews.find({}))
    reported = [r for r in reviews if len(r.get("reported_by", [])) >= min_reports]
    reported.sort(key=lambda r: len(r.get("reported_by", [])), reverse=True)
    out = []
    for r in reported[:50]:
        rest = db.restaurants.find_one({"_id": r["restaurant_id"]})
        item = serialize(r)
        item["report_count"] = len(r.get("reported_by", []))
        item["restaurant_name"] = rest["name"] if rest else "Unknown restaurant"
        out.append(item)
    return out


@app.get("/analytics")
def get_analytics():
    restaurants = list(db.restaurants.find({}, {"avg_rating": 1, "trust_adjusted_rating": 1, "google_rating": 1, "review_count": 1, "cuisine": 1, "area": 1}))
    reviews = list(db.reviews.find({}, {"trust_flag": 1, "overall_sentiment": 1, "star_rating": 1}))
    total = len(reviews)
    verified = sum(r.get("trust_flag") == "verified" for r in reviews)
    positive = sum((r.get("overall_sentiment") or 0) >= 0.15 for r in reviews)
    negative = sum((r.get("overall_sentiment") or 0) <= -0.15 for r in reviews)
    neutral = max(0, total - positive - negative)
    ratings = [_rating(r) for r in restaurants if _rating(r) > 0]
    cuisine_counts = {}
    area_counts = {}
    for r in restaurants:
        for c in r.get("cuisine") or []: cuisine_counts[c] = cuisine_counts.get(c, 0) + 1
        if r.get("area"): area_counts[r["area"]] = area_counts.get(r["area"], 0) + 1
    positive_rate = round(positive / total * 100, 1) if total else 0
    verified_rate = round(verified / total * 100, 1) if total else 0
    return {
        "restaurants": len(restaurants), "reviews": total,
        "verified_reviews": verified,
        "positive_reviews": positive,
        "verified_rate": verified_rate,
        "positive_rate": positive_rate,
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
        "sentiment": {"positive": positive, "neutral": neutral, "negative": negative},
        "top_cuisines": sorted(cuisine_counts.items(), key=lambda x: x[1], reverse=True)[:8],
        "top_cities": sorted(area_counts.items(), key=lambda x: x[1], reverse=True)[:10],
    }


@app.get("/recommendations/me")
def get_my_recommendations(area: Optional[str] = None, current_user: str = Depends(get_current_user)):
    user = db.users.find_one({"_id": current_user})
    liked = user.get("liked_restaurant_ids", []) if user else []
    all_restaurants = list(db.restaurants.find({}))
    candidate_ids = None
    if area and area.lower() != "all":
        candidate_ids = {r["_id"] for r in all_restaurants if r.get("area") == area}
    rec_ids = recommend_for_user(liked, all_restaurants, top_n=8, candidate_ids=candidate_ids)
    return [serialize_for_list(r) for r in all_restaurants if r.get("_id") in rec_ids]


@app.post("/like/{restaurant_id}")
def like_restaurant(restaurant_id: str, current_user: str = Depends(get_current_user)):
    if not db.restaurants.find_one({"_id": restaurant_id}):
        raise HTTPException(status_code=404, detail="Restaurant not found")
    db.users.update_one({"_id": current_user}, {"$addToSet": {"liked_restaurant_ids": restaurant_id}})
    return {"status": "ok", "liked": True}


@app.delete("/like/{restaurant_id}")
def unlike_restaurant(restaurant_id: str, current_user: str = Depends(get_current_user)):
    db.users.update_one({"_id": current_user}, {"$pull": {"liked_restaurant_ids": restaurant_id}})
    return {"status": "ok", "liked": False}


@app.get("/favorites")
def favorites(current_user: str = Depends(get_current_user)):
    user = db.users.find_one({"_id": current_user})
    ids = user.get("liked_restaurant_ids", []) if user else []
    return [serialize_for_list(r) for r in db.restaurants.find({"_id": {"$in": ids}})]


@app.get("/me")
def get_me(current_user: str = Depends(get_current_user)):
    user = db.users.find_one({"_id": current_user})
    if not user: raise HTTPException(status_code=404, detail="User not found")
    return serialize(user)


@app.patch("/me")
def update_me(update: ProfileUpdate, current_user: str = Depends(get_current_user)):
    fields = {k: v for k, v in update.model_dump().items() if v is not None}
    if fields: db.users.update_one({"_id": current_user}, {"$set": fields})
    return get_me(current_user)


@app.post("/me/change-password")
def change_password(payload: PasswordChange, current_user: str = Depends(get_current_user)):
    user = db.users.find_one({"_id": current_user})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(payload.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if not PASSWORD_RE.match(payload.new_password):
        raise HTTPException(
            status_code=400,
            detail="New password must be 8+ characters with an uppercase letter, "
                   "a number, and a special character.",
        )
    db.users.update_one({"_id": current_user}, {"$set": {"password_hash": hash_password(payload.new_password)}})
    return {"status": "ok"}


@app.get("/me/reviews")
def get_my_reviews(current_user: str = Depends(get_current_user)):
    reviews = [serialize(r) for r in db.reviews.find({"user_id": current_user}).sort("created_at", -1)]
    ids = list({r["restaurant_id"] for r in reviews})
    names = {r["_id"]: r.get("name", "Unknown restaurant") for r in db.restaurants.find({"_id": {"$in": ids}})}
    for r in reviews: r["restaurant_name"] = names.get(r["restaurant_id"], "Unknown restaurant")
    return reviews


@app.post("/contact")
def submit_contact(msg: ContactMessage):
    db.contact_messages.insert_one({
        "_id": f"contact_{uuid.uuid4().hex[:10]}", **msg.model_dump(), "submitted_at": datetime.utcnow()
    })
    return {"status": "ok"}


@app.get("/dashboard")
def dashboard(current_user: str = Depends(get_current_user)):
    analytics = get_analytics()
    user = db.users.find_one({"_id": current_user}) or {}
    return {
        "analytics": analytics,
        "user": {"name": user.get("name", "User"), "review_count": user.get("review_count", 0), "likes": len(user.get("liked_restaurant_ids", []))},
    }
