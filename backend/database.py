import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "").strip()
DB_NAME = os.getenv("MONGO_DB", "food_review_platform").strip() or "food_review_platform"

if MONGO_URI:
    from pymongo import MongoClient
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    db = client[DB_NAME]
    # Fail early when the credentials/URI are wrong instead of showing a fake
    # connected state and failing later on the first query.
    client.admin.command("ping")
    print(f"[database] Connected to real MongoDB: {DB_NAME}")
else:
    import mongomock
    client = mongomock.MongoClient()
    db = client[DB_NAME]
    print("[database] No MONGO_URI set — using in-memory mongomock DB.")
