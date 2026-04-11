"""
墨水屏 × Claude — 中转服务器 v3
支持 MCP（自定义连接器），Claude 对话框直接推送到墨水屏。
"""

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import json, os, datetime, secrets, asyncio, uuid

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


# ── MCP Protocol (Custom Connector for Claude) ──
MCP_TOOLS = [
    {
        "name": "push_to_eink",
       "description": "推送文字内容到用户的电子墨水屏。屏幕分辨率400x300，支持【黑、白、红】三色显示。重要：当你想要强调某些文字时，请务必使用 XML 标签来格式化：红色文字用 <r>包裹</r>，加粗用 <b>包裹</b>，斜体用 <i>包裹</i>，巨型排版用 <big>包裹</big>（用于单独放大的单词或短语，会自动铺满屏幕），且支持嵌套（如 <big><b><r>重点</r></b></big>）。内容控制在100字以内，避免复杂的emoji。",
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要显示在墨水屏上的文字内容，包含格式化标签（<r>, <b>, <i>）。The text to display on the e-ink screen."
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "get_eink_status",
        "description": "查看墨水屏当前显示的内容和最近推送历史。Check what's currently displayed on the e-ink screen and recent push history.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def handle_mcp_request(body: dict) -> dict:
    """Handle a single MCP JSON-RPC request."""
    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "eink-display",
                    "version": "1.0.0"
                }
            }
        }

    elif method == "notifications/initialized":
        # This is a notification, no response needed
        return None

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS}
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        if tool_name == "push_to_eink":
            text = args.get("text", "")
            if not text:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": "错误：文字内容不能为空"}],
                        "isError": True
                    }
                }

            # Push the content (same logic as /api/letter but without token check)
            data = {
                "text": text,
                "date": datetime.date.today().isoformat(),
                "updated_at": datetime.datetime.now().isoformat(),
            }
            open(DATA_FILE, "w").write(json.dumps(data, ensure_ascii=False))
            append_history(data)

            # Notify SSE subscribers
            msg = json.dumps(data, ensure_ascii=False)
            for q in subscribers:
                q.put_nowait(msg)

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"已发送 ✦ 内容：「{text[:50]}{'...' if len(text)>50 else ''}」约10秒后墨水屏刷新完成。"}]
                }
            }

        elif tool_name == "get_eink_status":
            current = {"text": "", "date": "", "updated_at": ""}
            if os.path.exists(DATA_FILE):
                current = json.loads(open(DATA_FILE).read())
            history_items = load_history()[-5:]
            status = f"当前显示: {current.get('text','(空)')}\n上次更新: {current.get('updated_at','无')}\n\n最近推送:\n"
            for h in reversed(history_items):
                status += f"  [{h.get('date','')}] {h.get('text','')[:40]}\n"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": status}]
                }
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"未知工具: {tool_name}"}],
                    "isError": True
                }
            }

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """MCP Streamable HTTP endpoint for Claude custom connector."""
    body = await request.json()

    # Handle batch requests
    if isinstance(body, list):
        results = []
        for item in body:
            r = handle_mcp_request(item)
            if r is not None:
                results.append(r)
        if len(results) == 1:
            return JSONResponse(results[0])
        return JSONResponse(results)

    # Single request
    result = handle_mcp_request(body)
    if result is None:
        return JSONResponse({"jsonrpc": "2.0", "result": {}})
    return JSONResponse(result)


@app.get("/mcp")
async def mcp_sse(request: Request):
    """MCP SSE endpoint for server-initiated messages."""
    async def event_gen():
        yield f": MCP SSE stream\n\n"
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(30)
            yield f": keepalive\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/static", StaticFiles(directory="static"), name="static")
