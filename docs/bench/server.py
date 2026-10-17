"""Minimal room hub: FastAPI WebSocket, in-memory fan-out, optional SQLite persist."""
import asyncio
import json
import os
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

PERSIST = os.environ.get("PERSIST", "0") == "1"
DB_PATH = os.environ.get("DB_PATH", "bench.db")
rooms: dict[str, set[asyncio.Queue]] = {}
state = {"seq": 0, "db": None}


@asynccontextmanager
async def lifespan(app):
    if PERSIST:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        db = await aiosqlite.connect(DB_PATH)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute(
            "CREATE TABLE message (seq INTEGER PRIMARY KEY, room TEXT, sender TEXT, body TEXT)"
        )
        await db.commit()
        state["db"] = db
    yield
    if state["db"]:
        await state["db"].close()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws/{room}")
async def ws(websocket: WebSocket, room: str):
    await websocket.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=100_000)
    subs = rooms.setdefault(room, set())
    subs.add(q)

    async def writer():
        while True:
            await websocket.send_text(await q.get())

    wt = asyncio.create_task(writer())
    try:
        while True:
            obj = json.loads(await websocket.receive_text())
            state["seq"] += 1
            obj["seq"] = state["seq"]
            if PERSIST:
                db = state["db"]
                await db.execute(
                    "INSERT INTO message VALUES (?,?,?,?)",
                    (obj["seq"], room, obj.get("from", ""), obj.get("body", "")),
                )
                await db.commit()
            out = json.dumps(obj)
            for s in subs:
                s.put_nowait(out)
    except WebSocketDisconnect:
        pass
    finally:
        subs.discard(q)
        wt.cancel()
