import re
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()

ASPECT_KEYWORDS = {
    "food": ["food", "taste", "flavour", "flavor", "dish", "spicy", "portion",
             "delicious", "menu", "biryani", "curry", "meal"],
    "service": ["service", "waiter", "staff", "wait", "server", "rude",
                "friendly", "attentive", "slow"],
    "price": ["price", "expensive", "cheap", "value", "cost", "affordable",
              "overpriced", "worth", "pricey"],
    "ambience": ["ambience", "ambiance", "decor", "music", "seating",
                 "atmosphere", "vibe", "noise", "lighting", "cozy"],
    "hygiene": ["clean", "hygiene", "dirty", "sanitary", "hygienic",
                "smell", "cleanliness"],
}


def split_sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def analyze_aspects(text: str) -> dict:
    """Returns per-aspect sentiment label: 'positive' | 'neutral' | 'negative' | None"""
    sentences = split_sentences(text)
    aspect_scores = {aspect: [] for aspect in ASPECT_KEYWORDS}

    for sentence in sentences:
        lower = sentence.lower()
        for aspect, keywords in ASPECT_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                score = analyzer.polarity_scores(sentence)["compound"]
                aspect_scores[aspect].append(score)

    result = {}
    for aspect, scores in aspect_scores.items():
        if scores:
            avg = sum(scores) / len(scores)
            result[aspect] = "positive" if avg > 0.15 else "negative" if avg < -0.15 else "neutral"
        else:
            result[aspect] = None
    return result


def overall_sentiment(text: str) -> float:
    return analyzer.polarity_scores(text)["compound"]
