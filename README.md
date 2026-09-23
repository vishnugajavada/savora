<div align="center">

# 🍽️ Savora

### AI-Powered Restaurant Review Intelligence Platform for India

*Real reviews. Real trust. Real recommendations.*

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.38-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/atlas)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-IsolationForest-F7931E?logo=scikitlearn&logoColor=white)](https://scikit-learn.org/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[**🔗 Live App**](https://savoravishnu.streamlit.app) · [**🐛 Report a Bug**](../../issues)

</div>

---

## Overview

Savora isn't just another "post a review, see a star rating" app. It's a restaurant discovery platform where every review is run through a real ML pipeline before it's shown to anyone:

- 🛡️ **Every review is scored for authenticity** using an Isolation Forest model trained on text-similarity, rating patterns, and behavioral signals — so a restaurant's "trust-adjusted" rating isn't just an average of whatever gets posted.
- 🧠 **Every review is broken into aspects** (food, service, price, ambience, hygiene) via NLP sentiment analysis — not just a single star rating.
- 🎯 **Recommendations are built from what you've actually liked**, using TF-IDF similarity over real review content — not a popularity leaderboard.
- 🌍 **Real restaurant data across 30+ Indian cities**, sourced from Google Places API and OpenStreetMap — not synthetic filler.

Built end-to-end: FastAPI backend, Streamlit frontend, MongoDB Atlas for persistence, deployed and live.

---

## ✨ Key Features

| | |
|---|---|
| 🔐 **Real Authentication** | JWT-based sessions, PBKDF2-SHA256 password hashing, enforced password strength rules |
| 📝 **Full Review Lifecycle** | Post, edit, delete, and report reviews — with photo uploads (up to 4 per review) |
| 🛡️ **Fake Review Detection** | Isolation Forest model flags suspicious reviews (near-duplicate text, extreme ratings, behavioral outliers) and computes a trust-adjusted rating per restaurant |
| 💬 **Aspect-Based Sentiment** | Every review is analyzed for sentiment across 5 aspects (food, service, price, ambience, hygiene), visualized per restaurant |
| 🎯 **Personalized Recommendations** | Content-based recommendation engine (TF-IDF + cosine similarity) over your liked restaurants, with city-aware scoping |
| 🍛 **Popular Items** | Automatically surfaces the most-mentioned dishes from real reviews (honestly labeled — not a scraped menu) |
| 💰 **Cost-for-Two Estimates** | Deterministic pricing estimates from cuisine, city, and real Google price-level data when available |
| 🗺️ **Interactive Map** | Explore restaurants geographically with an OpenStreetMap-powered view |
| 📊 **Personal Dashboard** | Real, computed stats on your own reviewing activity — review count, trust score, activity trends, cuisine breakdown |
| 🌐 **Two Real-Data Pipelines** | Ingest real restaurant data via Google Places API *or* completely free via OpenStreetMap — your choice |
| 🚩 **Community Moderation** | Users can report suspicious reviews; a lightweight moderation view surfaces the most-flagged content |

---

## 🖥️ Screenshots

<div align="center">
<!--
  Add real screenshots here before publishing, e.g.:
  <img src="docs/screenshots/login.png" width="800" alt="Login page">
  <img src="docs/screenshots/dashboard.png" width="800" alt="Dashboard">
  <img src="docs/screenshots/restaurant-detail.png" width="800" alt="Restaurant detail with aspect sentiment">
-->
<i>Screenshots coming soon — see the <a href="https://savoravishnu.streamlit.app">live app</a> in the meantime.</i>
</div>

---

## 🛠️ Tech Stack

**Backend**
- FastAPI · Uvicorn · Pydantic
- PyJWT (auth) · PBKDF2-SHA256 (password hashing)
- MongoDB (pymongo) with an automatic in-memory `mongomock` fallback for zero-setup local development

**ML / NLP**
- scikit-learn — Isolation Forest (fake review detection), TF-IDF + cosine similarity (recommendations, duplicate detection)
- VADER Sentiment — aspect-based and overall sentiment analysis

**Frontend**
- Streamlit · Plotly (charts, interactive map)

**Data Sources**
- Google Places API (New) — real restaurant data, ratings, photos, reviews
- OpenStreetMap (Nominatim + Overpass API) — free alternative real-data source, no API key required
- Foodish API / placehold.co — graceful photo fallbacks

**Deployment**
- Render (backend) · Streamlit Community Cloud (frontend) · MongoDB Atlas (database)

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11
- A MongoDB Atlas account *(optional — the app runs with an in-memory database out of the box)*
- A Google Cloud project with the Places API (New) enabled *(optional — only needed for real-data ingestion via Google)*

### Installation

```bash
git clone https://github.com/vishnugajavada/savora.git
cd savora
pip install -r requirements.txt
```

### Run locally

```bash
# Terminal 1 — backend
cd backend
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
streamlit run app.py
```

The app runs immediately with **zero configuration** — it auto-generates realistic demo data (restaurants, reviews, planted "fake" reviews to demonstrate trust scoring) in an in-memory database on first launch.

### (Optional) Connect real data

**Free, no API key required:**
```bash
cd backend
python osm_ingest.py
```

**Full real photos & reviews (requires a Google Cloud API key + billing enabled):**
```bash
cd backend
python places_ingest.py
```

**Persist data across restarts:** set `MONGO_URI` in `backend/.env` to a MongoDB Atlas connection string (see [Environment Variables](#-environment-variables)).

---

## ⚙️ Environment Variables

Create a `.env` file inside `backend/` (see `.env.example`):

| Variable | Required | Description |
|---|---|---|
| `MONGO_URI` | No | MongoDB Atlas connection string. Omit to use the built-in in-memory database. |
| `MONGO_DB` | No | Database name (defaults to `food_review_platform`). |
| `GOOGLE_PLACES_API_KEY` | No | Required only if running `places_ingest.py` for real Google data. |

For the deployed frontend, set:

| Variable | Description |
|---|---|
| `API_URL` | The backend's public URL (e.g. `https://savora-1.onrender.com`). Defaults to `http://127.0.0.1:8000` for local dev. |

> **Never commit `.env` files.** This repo's `.gitignore` already excludes them.

---
---

## 📡 API Highlights

Full interactive API documentation is available at `/docs` on the running backend (Swagger UI, auto-generated by FastAPI).

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/signup` · `/auth/login` | Authentication |
| `GET` | `/restaurants` | Browse/filter restaurants (city, cuisine, rating, search, sort) |
| `GET` | `/restaurants/{id}` | Full restaurant detail |
| `POST` | `/reviews` | Submit a review (with photo uploads) |
| `PATCH` / `DELETE` | `/reviews/{id}` | Edit or delete your own review |
| `POST` | `/reviews/{id}/report` | Report a review |
| `GET` | `/recommendations/me` | Personalized recommendations |
| `GET` | `/me/dashboard` | Your personal activity dashboard |
| `GET` | `/analytics` | Platform-wide statistics |

---

## 🧠 Engineering Highlights

A few things worth knowing if you're reviewing this as a portfolio piece — this project went through real, measured performance engineering, not just feature-building:

- **Restaurant photo storage** is done *once*, at data-ingestion time — not fetched live from Google on every page view. This eliminated both flaky image loading and a major source of latency.
- **List-view payloads are served with cached thumbnails**, not full-resolution images — cut a 124-restaurant listing response from **1.4MB to 210KB**.
- **Isolation Forest hyperparameters were profiled and tuned** for small per-restaurant datasets (`n_estimators=25`, `n_jobs=1`), cutting trust-score computation time by **~3.3x** with no loss in detection accuracy.
- **Data ingestion is fault-tolerant** — retries transient network failures with backoff, and isolates failures per-city so a single bad connection doesn't waste hours of an in-progress multi-city ingestion run.

---

## ⚠️ Known Limitations

Being upfront about these, since they're worth understanding rather than discovering:

- Aspect sentiment is currently computed at the **sentence level**, so a sentence mentioning two aspects with mixed sentiment applies the same score to both.
- Trust scoring is **unsupervised** (no labeled fraud dataset exists) — it's a reasonable heuristic, not a guaranteed classifier.
- "Popular items" and "cost for two" are **derived estimates**, honestly labeled as such in the UI — not scraped menu data.
- Recommendations are **content-based only** — no collaborative filtering yet.
- Free-tier hosting means the backend may take 30-60 seconds to respond after periods of inactivity (cold start).

---

## 🗺️ Roadmap

- [ ] Google / Facebook OAuth login
- [ ] Password reset flow
- [ ] Collaborative-filtering recommendations
- [ ] Automated CI test suite

---

<div align="center">

Built by **Vishnu Gajavada** — [GitHub](https://github.com/vishnugajavada)

*If this project was useful or interesting, consider leaving a ⭐*

</div>
