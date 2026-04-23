from fastapi import FastAPI

app = FastAPI(title="x-social-trader", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Real /ready + /metrics land in OBS-02/OBS-03 (phase 3)."""
    return {"status": "ok"}
