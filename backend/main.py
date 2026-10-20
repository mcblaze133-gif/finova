from pathlib import Path
from time import perf_counter
from contextlib import asynccontextmanager

import httpx
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException

from backend.storage import initialize
from backend import storage
from backend.api import router, TASKS
import asyncio
from backend.model import reserve_probe, ModelUnavailable
from backend.excel_api import router as excel_router, JOBS
from backend.analysis_reports import router as report_router, TASKS as REPORT_TASKS


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    with storage.database() as db:
        db.execute("UPDATE research_runs SET status='interrupted',stage='interrupted',error='Service restarted before completion.' WHERE status IN ('queued','running')")
        db.execute("UPDATE excel_exports SET status='interrupted',error='Service restarted before workbook completion.' WHERE status IN ('queued','building')")
        db.execute("UPDATE company_update_runs SET status='interrupted',stage='interrupted',error='Service restarted before online refresh completion.' WHERE status IN ('queued','running')")
        db.execute("UPDATE analysis_reports SET status='interrupted',stage='interrupted',error='Report interrupted by service restart.' WHERE status IN ('queued','running')")
    yield
    for task in list(TASKS | JOBS | REPORT_TASKS):
        task.cancel()
    if TASKS | JOBS | REPORT_TASKS:
        await asyncio.gather(*list(TASKS | JOBS | REPORT_TASKS), return_exceptions=True)


app = FastAPI(title="Finova", version="0.3.0", lifespan=lifespan)
app.include_router(router)
app.include_router(excel_router)
app.include_router(report_router)


@app.middleware('http')
async def local_only(request, call_next):
    from fastapi.responses import JSONResponse
    host = request.headers.get('host', '').split(':')[0].lower()
    if host not in ('127.0.0.1', 'localhost', 'test', 'testserver'):
        return JSONResponse(status_code=403, content={'detail': 'Local access only.'})
    origin = request.headers.get('origin')
    if origin and origin not in ('http://localhost:8000', 'http://127.0.0.1:8000'):
        return JSONResponse(status_code=403, content={'detail': 'Cross-origin browser access denied.'})
    if request.headers.get('sec-fetch-site') == 'cross-site':
        return JSONResponse(status_code=403, content={'detail': 'Cross-site browser access denied.'})
    return await call_next(request)

PROJECT_DIR = Path(__file__).resolve().parent.parent
MODEL = "gemini-3.1-flash-lite"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "Finova backend",
    }


@app.post("/model/test")
async def test_model():
    config = dotenv_values(
        PROJECT_DIR / ".env",
        encoding="utf-8-sig",
    )
    key = (config.get("GEMINI_API_KEY") or "").strip()

    if not key:
        raise HTTPException(503, "Gemini key is missing.")
    if (config.get('GEMINI_FREE_TIER_CONFIRMED') or '').lower() != 'true':
        raise HTTPException(503, 'Free-tier account is not confirmed. Model calls disabled.')
    try:
        reserve_probe()
    except ModelUnavailable as exc:
        raise HTTPException(429, str(exc)) from None

    payload = {
        "contents": [{
            "parts": [{"text": "Reply with exactly: SIGNALAI_OK"}]
        }],
        "generationConfig": {"maxOutputTokens": 128},
    }

    started = perf_counter()

    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/"
                f"v1beta/models/{config.get('GEMINI_MODEL', MODEL)}:generateContent",
                headers={"x-goog-api-key": key},
                json=payload,
            )
    except httpx.RequestError:
        raise HTTPException(504, "Gemini connection failed or timed out.")

    if response.status_code != 200:
        raise HTTPException(
            502,
            f"Gemini returned HTTP {response.status_code}. "
            "No automatic retry was made.",
        )

    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid response object")
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Missing candidates")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ValueError("Invalid candidate")
        content = candidate.get("content")
        if not isinstance(content, dict):
            raise ValueError("Missing content")
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError("Missing response parts")
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError("Invalid response part")
            if "thought" in part and not isinstance(part["thought"], bool):
                raise ValueError("Invalid thought marker")
            if "text" in part and not isinstance(part["text"], str):
                raise ValueError("Invalid response text")
        answer = "".join(
            part.get("text", "")
            for part in parts
            if not part.get("thought", False)
        ).strip()
        if not answer:
            raise ValueError("Missing response text")
    except (ValueError, AttributeError, TypeError, IndexError, KeyError):
        raise HTTPException(502, "Gemini returned an unexpected response.")

    return {
        "passed": answer == "SIGNALAI_OK",
        "model": config.get('GEMINI_MODEL', MODEL),
        "response": answer,
        "seconds": round(perf_counter() - started, 2),
        "usage": data.get("usageMetadata", {}),
    }
