"""
墨水屏 × Claude — 中转服务器 v2
支持 SSE 实时推送，不再需要轮询。
"""

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json, os, datetime, secrets, asyncio

app = FastAPI(title="E-Ink × Claude Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_FILE = "latest_letter.json"
HISTORY_FILE = "history.json"

# SSE subscribers
subscribers: list[asyncio.Queue] = []


# ── Token ──
def get_token():
    t = os.environ.get("EINK_TOKEN")
    if t:
        return t
    tf = "token.txt"
    if os.path.exists(tf):
        return open(tf).read().strip()
    t = secrets.token_urlsafe(12)
    open(tf, "w").write(t)
    print(f"\n  ★ 推送密钥: {t}")
    print(f"  ★ 设置环境变量 EINK_TOKEN 可自定义\n")
    return t


TOKEN = get_token()


def check_token(token: Optional[str]):
    if not token or token != TOKEN:
        raise HTTPException(403, "密钥错误")


# ── History ──
def load_history():
    if os.path.exists(HISTORY_FILE):
        return json.loads(open(HISTORY_FILE).read())
    return []


def append_history(entry):
    h = load_history()[-49:]
    h.append(entry)
    open(HISTORY_FILE, "w").write(json.dumps(h, ensure_ascii=False, indent=2))


# ── Models ──
class Note(BaseModel):
    text: str = ""
    date: Optional[str] = None
    token: Optional[str] = None


# ── Routes ──
@app.get("/api/latest")
def get_latest():
    if os.path.exists(DATA_FILE):
        return json.loads(open(DATA_FILE).read())
    return {"text": "", "date": "", "updated_at": ""}


@app.post("/api/letter")
async def push(note: Note):
    check_token(note.token)
    data = {
        "text": note.text,
        "date": note.date or datetime.date.today().isoformat(),
        "updated_at": datetime.datetime.now().isoformat(),
    }
    open(DATA_FILE, "w").write(json.dumps(data, ensure_ascii=False))
    append_history(data)

    # Notify all SSE subscribers instantly
    msg = json.dumps(data, ensure_ascii=False)
    for q in subscribers:
        await q.put(msg)

    return {"status": "ok", "data": data}


@app.get("/api/stream")
async def sse(request: Request):
    """Server-Sent Events — 实时推送，无需轮询"""
    queue: asyncio.Queue = asyncio.Queue()
    subscribers.append(queue)

    async def event_gen():
        try:
            # Send current content on connect
            if os.path.exists(DATA_FILE):
                current = open(DATA_FILE).read()
                yield f"data: {current}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield f": keepalive\n\n"
        finally:
            subscribers.remove(queue)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/version")
def version():
    if os.path.exists(DATA_FILE):
        d = json.loads(open(DATA_FILE).read())
        return {"updated_at": d.get("updated_at", "")}
    return {"updated_at": ""}


@app.get("/api/history")
def history(n: int = Query(10, le=50)):
    return {"items": load_history()[-n:]}


@app.get("/api/whoami")
def whoami():
    return {"token_hint": TOKEN[:4] + "····", "status": "running"}


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/manifest.json")
def manifest():
    return {
        "name": "墨水屏 × Claude",
        "short_name": "E-Ink",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1714",
        "theme_color": "#1a1714",
        "icons": [],
    }


app.mount("/static", StaticFiles(directory="static"), name="static")
