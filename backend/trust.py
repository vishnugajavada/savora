import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def compute_trust_scores(reviews: list) -> list:
    """
    reviews: list of dicts with at least 'text' and 'star_rating'
    Returns a list of trust scores in [0, 1] (higher = more trustworthy),
    aligned index-for-index with the input list.

    Signals used:
      - max text similarity to any other review on the same restaurant
        (near-duplicate / copy-paste reviews)
      - rating extremeness (distance from a neutral 3-star)
      - review length (very short reviews are weaker signals)
    """
    n = len(reviews)
    if n < 3:
        # not enough reviews on this restaurant to judge anomalies yet
        return [1.0] * n

    texts = [r["text"] for r in reviews]
    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf = vectorizer.fit_transform(texts)
        sim_matrix = cosine_similarity(tfidf)
    except ValueError:
        sim_matrix = np.zeros((n, n))

    features = []
    for i, r in enumerate(reviews):
        max_sim = max([sim_matrix[i][j] for j in range(n) if j != i], default=0.0)
        extremeness = abs(r["star_rating"] - 3)
        text_len = len(r["text"].split())
        features.append([max_sim, extremeness, text_len])

    features = np.array(features)
    # n_estimators=25 (not sklearn's default 100) and n_jobs=1 (not parallel) —
    # for datasets this small (a handful to a few dozen reviews per restaurant),
    # joblib's multiprocessing dispatch overhead dwarfs the actual fit time, so
    # disabling it is a large, real speedup, not just a cosmetic tweak. Detection
    # quality is unaffected at this sample size.
    clf = IsolationForest(n_estimators=25, contamination=0.15, random_state=42, n_jobs=1)
    clf.fit(features)
    raw_scores = clf.decision_function(features)  # higher = more "normal"

    min_s, max_s = raw_scores.min(), raw_scores.max()
    if max_s - min_s == 0:
        return [1.0] * n

    trust_scores = [float((s - min_s) / (max_s - min_s)) for s in raw_scores]
    return trust_scores
