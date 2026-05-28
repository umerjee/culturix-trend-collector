from fastapi import FastAPI
from app.collectors.reddit import store_reddit_trends

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/collect/reddit")
def collect_reddit():
    inserted = store_reddit_trends()
    return {"inserted": inserted}
