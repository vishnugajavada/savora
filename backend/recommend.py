from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


_similarity_cache = {}


def _fingerprint(restaurants):
    return tuple((r.get("_id"), r.get("combined_review_text") or r.get("name", "")) for r in restaurants)


def _get_similarity(restaurants):
    key = _fingerprint(restaurants)
    cached = _similarity_cache.get("matrix")
    if cached and cached[0] == key:
        return cached[1], cached[2]

    ids = [r["_id"] for r in restaurants]
    texts = [r.get("combined_review_text") or r.get("name", "") for r in restaurants]
    if len(texts) < 2:
        return ids, None

    vectorizer = TfidfVectorizer(stop_words="english", max_features=4000)
    tfidf = vectorizer.fit_transform(texts)
    sim = cosine_similarity(tfidf)
    _similarity_cache["matrix"] = (key, ids, sim)
    return ids, sim


def invalidate_cache():
    _similarity_cache.clear()


def recommend_similar(restaurant_id: str, restaurants: list, top_n: int = 3, candidate_ids=None) -> list:
    ids, sim = _get_similarity(restaurants)
    if sim is None or restaurant_id not in ids:
        return []

    idx = ids.index(restaurant_id)
    scores = [(i, float(s)) for i, s in enumerate(sim[idx]) if i != idx]
    if candidate_ids is not None:
        scores = [(i, s) for i, s in scores if ids[i] in candidate_ids]
    scores.sort(key=lambda x: x[1], reverse=True)
    return [ids[i] for i, _ in scores[:top_n]]


def recommend_for_user(liked_restaurant_ids: list, restaurants: list, top_n: int = 5, candidate_ids=None) -> list:
    if not liked_restaurant_ids:
        return []

    ids, sim = _get_similarity(restaurants)
    if sim is None:
        return []

    id_to_idx = {rid: i for i, rid in enumerate(ids)}
    votes = {}
    for rid in liked_restaurant_ids:
        idx = id_to_idx.get(rid)
        if idx is None:
            continue
        scores = [(i, float(s)) for i, s in enumerate(sim[idx]) if i != idx]
        if candidate_ids is not None:
            scores = [(i, s) for i, s in scores if ids[i] in candidate_ids]
        scores.sort(key=lambda x: x[1], reverse=True)
        for i, _ in scores[:top_n]:
            sim_id = ids[i]
            if sim_id not in liked_restaurant_ids:
                votes[sim_id] = votes.get(sim_id, 0) + 1

    ranked = sorted(votes.items(), key=lambda x: x[1], reverse=True)
    return [rid for rid, _ in ranked[:top_n]]
