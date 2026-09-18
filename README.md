# India Food Review Intelligence Platform

A restaurant review platform where anyone can sign up, post a review with photos, and
browse others' reviews to decide whether to visit — but with several things a plain
review app doesn't have:

- **Real accounts** — email/password signup and login, JWT-based sessions, passwords
  hashed with salted PBKDF2-SHA256 (Python's stdlib `hashlib` — deliberately avoids
  bcrypt/native compiled dependencies, which can fail to install on Windows without
  Visual Studio Build Tools).
- **Personal Details page** — view your account info, optionally add a phone number and
  location, and see every review you've personally posted, all in one place.
- **Contact Us page** — a simple message form, stored server-side (`/contact` endpoint).
- **Clean light theme** — white background throughout, set via `.streamlit/config.toml`.
- **Real restaurant data across India** — restaurants, addresses, photos, and real Google
  reviews pulled from Google Places API (New) across 30+ cities spanning every region of
  India, run through the same ML pipeline as user-submitted reviews. (Falls back to
  realistic synthetic data automatically if no API key is configured, so it still runs
  with zero setup.)
- **Photo uploads on reviews** — users can attach up to 4 photos per review; anyone
  browsing that restaurant sees photos everyone else has posted, right alongside the text.
- **Popular items** — commonly-mentioned dish names extracted from a restaurant's reviews
  (e.g. "Biryani", "Butter Chicken") — an honest stand-in for "recommended items" since no
  free real menu-data source exists; labeled clearly as what reviewers mention, not a menu.
- **Estimated cost for two** — a deterministic estimate based on cuisine, city, and Google's
  price level when available; labeled as an estimate, not real menu pricing.
- **Aspect-based sentiment** — every review is broken down into food / service / price /
  ambience / hygiene scores, not just one star rating (radar chart per restaurant).
- **Fake-review detection** — an Isolation Forest model scores every review's trustworthiness
  (duplicate/burst-posted reviews get flagged) and restaurants show a *trust-adjusted rating*
  alongside the raw average.
- **Personalized recommendations** — a content-based engine (TF-IDF over each restaurant's
  review text) recommends similar restaurants based on what you've liked.

Users can filter restaurants by **area** and **cuisine type** from the sidebar.

---

## Project structure

```
food-review-platform/
├── backend/
│   ├── main.py            FastAPI app — all API endpoints (incl. auth + photo proxy)
│   ├── auth.py            Password hashing (PBKDF2-SHA256, stdlib) + JWT sessions
│   ├── database.py        MongoDB connection (Atlas, or in-memory mock if no URI set)
│   ├── nlp.py             Aspect-based sentiment analysis (VADER)
│   ├── trust.py           Fake-review detection (Isolation Forest)
│   ├── recommend.py       Recommendation engine (TF-IDF content similarity)
│   ├── seed_data.py       Generates realistic synthetic sample data (default, no setup)
│   └── places_ingest.py   Fetches REAL restaurants/photos/reviews across 30+ Indian
│                          cities via Google Places API (New) — used automatically
│                          when GOOGLE_PLACES_API_KEY is set
│   └── osm_ingest.py      Fetches REAL restaurant listings across 30+ Indian cities
│                          from OpenStreetMap — completely free, no API key or
│                          billing account needed, ever
├── frontend/
│   └── app.py           Streamlit UI — filters, radar charts, reviews, recommendations
├── requirements.txt
├── .env.example
└── README.md
```

## How to run it — quick start (no setup required)

This runs immediately with an in-memory database that auto-seeds sample restaurant data
across **30+ Indian cities spanning every region** (North, South, East, West, and Central
India — roughly 120 restaurants total, every one with an image), with some planted fake
reviews so the trust-detection feature has something to catch. No MongoDB account or
Google API key needed to try it out — you'll sign up with any email and a password
(8+ characters, one uppercase letter, one number, one special character)
to use the app.

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Start the backend** (in one terminal)
```bash
cd backend
uvicorn main:app --reload --port 8000
```
The first request will auto-seed the database. Visit `http://localhost:8000/docs` to see
the interactive API docs.

**3. Start the frontend** (in a second terminal)
```bash
cd frontend
streamlit run app.py
```
This opens `http://localhost:8501` in your browser. **Sign up** with any name/email and a
password meeting the strength rule shown on screen (e.g. `Hyderabad@123`) — this creates
a real hashed-password account in the database — then filter by city/cuisine,
expand a restaurant to see its aspect radar chart, post a review, and see the trust badge on
each review update live.

## Using real restaurants, photos, and reviews across India (Google Places API)

By default the app uses synthetic sample data (with placeholder images) so it runs with
zero setup. To pull real restaurants across 30+ Indian cities — with real addresses,
real photos, and real Google reviews already
run through the aspect-sentiment and trust-scoring pipeline:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create/select a project
2. **Enable billing** on the project — required by Google for Places API (New), but a
   recurring free monthly credit comfortably covers a portfolio-scale project (this app
   only issues ~8 search requests to build its dataset)
3. **APIs & Services → Library** → enable **"Places API (New)"** — search for that exact
   name. The old "Places API" listing is Legacy and can no longer be enabled on new projects.
4. **APIs & Services → Credentials** → Create API key → restrict it to "Places API (New)"
5. Copy `.env.example` to `.env` and set `GOOGLE_PLACES_API_KEY=your_key_here`
6. Run the ingestion script:
   ```bash
   cd backend
   python places_ingest.py
   ```
   Expect this to take a few minutes, not seconds — it's making real API calls across
   30+ cities and downloading a real photo for every restaurant Google actually has
   one for (only restaurants with genuinely zero Google photos fall back to a
   Foodish/placeholder image). Speed comes from downloading up to 15 photos in
   parallel, not from limiting how many restaurants get a real photo.

   The script retries transient network failures (timeouts, SSL handshake issues —
   normal on real networks over a long-running script) automatically, and if one city
   fails entirely after retries, it's skipped so the run continues to the next city
   rather than crashing. One honest caveat: without a persistent MongoDB (see below),
   all ingested data lives only in that one Python process's memory — if the script
   is killed outright (not just a single city failing, but the whole process dying),
   you'd need to re-run it from scratch. Connecting MongoDB Atlas removes this risk
   entirely, since data would already be saved as each city completes.
7. Restart the backend so it picks up the freshly-ingested data.

Restaurant photos are downloaded and resized ONCE at ingestion time and stored directly
in the database — never fetched live from Google while someone is browsing the app.
That's a deliberate choice: fetching live on every page view was slow and occasionally
showed broken images when a fetch failed transiently; ingesting once is both faster to
browse and more reliable.

Real restaurants start with **no reviews** until real Google reviews are found for them
(via the same request) or your signed-up users post some — this is realistic (a fresh
platform starts empty of user content), unlike the synthetic data which is pre-populated
with sample reviews for demo purposes.

## Using real restaurants — completely free, no billing (OpenStreetMap)

If you'd rather not deal with Google Cloud billing at all, `osm_ingest.py` pulls real
restaurant listings (name, address, coordinates, cuisine) across the same 30+ Indian
cities from **OpenStreetMap** — no API key, no signup, no billing account, ever. This
is genuinely free with no conditions attached, unlike Google's "free tier" (which still
requires enabling billing) or Foursquare/Yelp (which now charge for anything beyond
bare listings).

```bash
cd backend
python osm_ingest.py
```

The trade-off: OpenStreetMap is a map database, not a review platform, so it has no
photos or reviews. Restaurants ingested this way get a real food photo from the free
Foodish API (matched loosely to cuisine) when available, falling back to a text
placeholder showing the restaurant's own name — never a random unrelated stock photo.
used for synthetic data (Foodish photo or name-labeled placeholder), and start at 0
reviews — same as the Google path when a place
happens to have none. Everything downstream (aspect sentiment, trust scoring,
recommendations) works identically once real reviews start coming in from your users.

This script talks to two free public services — Nominatim (geocoding) and Overpass
(the OSM query engine) — both request a modest, polite request rate, which the script
already respects with small delays between calls.

## Using a real, persistent MongoDB (recommended before deploying / for your resume)

By default the app uses `mongomock` — a fully in-memory stand-in with the same query API
as real MongoDB, which is why it needs zero setup. To switch to a real database:

1. Create a free cluster at [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Copy `.env.example` to `.env` and paste your connection string into `MONGO_URI`
3. Restart the backend — it will auto-seed the real database on first run

## Auth notes

- Every write action (posting a review, liking a restaurant) requires a logged-in user —
  the backend rejects these with `401` if no valid token is sent, so a review's author is
  always whoever is actually logged in, not something the client can spoof.
- Tokens are JWTs valid for 7 days, stored in Streamlit's `session_state` (browser session
  only — logging out or closing the tab clears it; nothing is written to browser storage).
- Set `JWT_SECRET` in `.env` before deploying anywhere public — the default value is fine
  for local/demo use only.

## Try the fake-review detection live

1. Expand any restaurant in the UI and look at the review badges — some will already say
   "⚠️ Flagged as suspicious" (these are the planted near-duplicate reviews from seeding).
2. Post a new review, then quickly post the exact same text again as a different rating —
   watch the trust score for the duplicate come back low.

## Deployment (free tier)

| Component | Where |
|---|---|
| Backend (FastAPI) | [Render](https://render.com) — set start command `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Database | [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) free tier |
| Frontend (Streamlit) | [Streamlit Community Cloud](https://streamlit.io/cloud) — set `API_URL` in `frontend/app.py` to your deployed backend URL before pushing |

## Performance

- **The restaurant LIST endpoint sends small cached thumbnails, not full-size photos.**
  Once real Google photos are ingested (stored as base64 for reliability — see below),
  sending ALL of them on every `GET /restaurants` call ballooned that single response
  past 1MB for ~124 restaurants, and Streamlit re-fetches this on nearly every click —
  this was the actual cause of the whole app feeling slow to navigate, not just the
  restaurant-detail view. The list endpoint now returns a ~5-10KB cached thumbnail per
  restaurant instead; the single-restaurant detail endpoint (used only for the one
  restaurant you're actually viewing) still returns full-resolution images.
- **Restaurant list uses numbered pagination** (10/20/50 per page) over a compact
  row layout, not the old expander-per-restaurant list. Clicking "View Details" opens
  a single detail panel below the list — reviews, aspect breakdown, and popular items
  are only ever fetched for the ONE restaurant being viewed, not for every restaurant
  on the page. The old expander-based layout re-executed every expander's contents
  (including a reviews fetch) on every single rerun regardless of collapsed state —
  this was the actual cause of the "taking forever" feeling, not just visual clutter.
- **Restaurant photos are fetched from Google ONCE, at ingestion time** (`places_ingest.py`),
  resized, and stored as base64 in the database — not fetched live from Google on every
  page view. Live-fetching on every view was the real cause of both flaky/missing images
  (transient failures, rate limits showing up as broken images) and slow page loads (a
  live Google round-trip per photo per view). Now photos are instant and reliable once
  ingested, since browsing never touches Google again.
- **IsolationForest is tuned for small per-restaurant datasets** (`n_estimators=25`,
  `n_jobs=1` instead of scikit-learn's defaults of 100 trees with multiprocess dispatch)
  — for datasets this size (a handful to a few dozen reviews per restaurant), joblib's
  parallel dispatch overhead dominates the actual fit time. This cut synthetic-data
  seeding from ~10s to ~3s with no change in detection quality.

## Design notes / known limitations (worth mentioning in an interview)

- **Aspect sentiment is sentence-level**, so a sentence mentioning two aspects with mixed
  sentiment (e.g. "food was great but service was slow") currently gets the same compound
  score applied to both — a natural next step is aspect-targeted sentiment (e.g. spaCy
  dependency parsing to isolate the clause per aspect) instead of whole-sentence scoring.
- **Trust scoring is unsupervised** (Isolation Forest on engineered features) since there's
  no labeled fraud data — this is realistic for a real-world deployment, but means the
  contamination rate (currently 15%) is a tunable assumption, not a learned constant.
- **Recommendations are content-based only** (TF-IDF similarity). With more user interaction
  data, adding collaborative filtering as a second strategy would be the natural upgrade.

## Tech stack

FastAPI · MongoDB (Atlas / mongomock) · scikit-learn (Isolation Forest, TF-IDF) ·
VADER sentiment · Streamlit · Plotly

## Professional UI + performance update

The frontend now uses a consistent production-style visual system: warm orange accent, charcoal/cream surfaces, rounded cards, responsive layouts, local food artwork, an upgraded authentication experience, restaurant cards, an Insights dashboard, trust badges, and cleaner review/detail flows.

Performance changes:

- Startup demo seeding uses a lightweight trust heuristic instead of fitting 100+ Isolation Forest models during every backend restart. Full Isolation Forest analysis is still used for real submitted reviews.
- Google Places ingestion is no longer triggered automatically during backend startup. Run `python places_ingest.py` explicitly when you want to refresh real data.
- Recommendation similarity is cached in memory instead of rebuilding a TF-IDF matrix for every recommendation request.
- Streamlit API reads are cached for 60 seconds, reducing repeated HTTP calls caused by Streamlit reruns.
- Restaurant list responses already use small cached thumbnails; the UI now also avoids external placeholder images for the demo dataset by using local assets.
- Personal review loading avoids an N+1 restaurant lookup pattern.
- Generated visual assets are stored locally under `frontend/assets/`, so the main UI does not depend on an external image service for its demo artwork.

### Run

```bash
# Terminal 1
cd backend
uvicorn main:app --reload --port 8000

# Terminal 2
cd frontend
streamlit run app.py
```

For real Google data, run the ingestion script manually after configuring `GOOGLE_PLACES_API_KEY` rather than waiting for API startup.

## Real restaurant data (recommended)

The application is designed so that **real-data ingestion is a separate job**. The web app does not call Google Places during FastAPI startup, which keeps Streamlit/FastAPI startup fast.

### Google Places API (real restaurants + ratings + selected reviews/photos)

1. Create a Google Cloud project and enable **Places API (New)**.
2. Enable billing and create a restricted API key.
3. Copy `.env.example` to `backend/.env` and set `GOOGLE_PLACES_API_KEY`.
4. From `backend/`, run one city at a time:

```bash
python ingest_real.py --city Hyderabad
```

Useful commands:

```bash
# Faster / cheaper catalog import without Google reviews
python ingest_real.py --city Hyderabad --no-reviews

# More coverage (2 pages per query)
python ingest_real.py --city Mumbai --pages 2

# Replace the current restaurant/review database (asks for confirmation)
python ingest_real.py --city Hyderabad --clear
```

The ingestion uses Google Places Text Search (New), stores the source as `Google Places`, and keeps the Google Maps URI when returned. The app can then run normally:

```bash
# Terminal 1
cd backend
uvicorn main:app --reload --port 8000

# Terminal 2
cd frontend
streamlit run app.py
```

### Important cost/security notes

Google Places is billed by the fields requested. In particular, `reviews`, `rating`, `userRatingCount`, and similar fields are in higher-priced tiers, so use small city-scoped imports and field masks rather than importing all of India on every run. Never commit an API key; restrict it in Google Cloud and rotate it immediately if it is ever exposed.

### Free alternative: OpenStreetMap

`backend/osm_ingest.py` can import real restaurant listings without a Google key. It is useful for names, locations, addresses and cuisine tags, but it does **not** provide the Google review/photo dataset that this application's review intelligence features need.
