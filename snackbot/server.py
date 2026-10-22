"""FastAPI: WebSocket(/ws), 음성(/stt), 카메라(/stream/front), frontend/ 정적 서빙.
controller를 부르기만 한다 (controller는 이 모듈을 모른다). 메시지 형식: docs/UI_DESIGN_PROMPT.md"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .vision import encode_jpeg

log = logging.getLogger(__name__)
UI_COMMANDS = ("resume", "estop", "restart")
STREAM_INTERVAL_S = 0.1


def draw_boxes(frame, boxes):
    if not boxes:
        return frame
    out = frame.copy()
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), (255, 200, 0), 2)
    return out


def mjpeg_chunk(frame, boxes=None):
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encode_jpeg(draw_boxes(frame, boxes)) + b"\r\n"


def create_app(controller, info, frame_fn=None, stt=None, static_dir="frontend"):
    clients = set()
    shared = {"loop": None, "queue": None}

    async def broadcast(event):
        for ws in list(clients):
            try:
                await ws.send_json(event)
            except Exception:
                clients.discard(ws)

    async def pump(queue):
        """이벤트를 들어온 순서대로 보낸다 (전송 작업이 하나라 순서가 섞이지 않는다)."""
        while True:
            await broadcast(await queue.get())

    def on_event(event):
        # controller 스레드에서 불린다 → 이벤트 루프 스레드로 넘긴다
        loop = shared["loop"]
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(shared["queue"].put_nowait, event)

    @asynccontextmanager
    async def lifespan(app):
        shared["queue"] = asyncio.Queue()
        shared["loop"] = asyncio.get_running_loop()
        task = asyncio.create_task(pump(shared["queue"]))
        yield
        shared["loop"] = None
        task.cancel()

    app = FastAPI(lifespan=lifespan)
    controller.subscribe(on_event)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        await ws.send_json(info)
        await ws.send_json(controller.snapshot())
        for msg in list(controller.history):
            await ws.send_json(msg)
        clients.add(ws)
        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type")
                if kind == "chat":
                    await run_in_threadpool(controller.chat, str(msg.get("text", "")), "text")
                elif kind == "command" and msg.get("name") in UI_COMMANDS:
                    await run_in_threadpool(controller.command, msg["name"])
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    @app.post("/stt")
    async def stt_endpoint(request: Request):
        if stt is None:
            raise HTTPException(503, "STT가 설정되지 않았어요 (config.yaml stt.chain)")
        wav = await request.body()
        try:
            text = await run_in_threadpool(stt.transcribe, wav)
        except Exception as e:
            log.warning("STT 실패: %s", e)
            controller.notify("음성 인식에 실패했어요")
            raise HTTPException(502, "STT 실패")
        text = (text or "").strip()
        if not text:
            controller.notify("못 알아들었어요")
            return {"text": ""}
        await run_in_threadpool(controller.chat, text, "voice")
        return {"text": text}

    @app.get("/stream/front")
    async def stream_front():
        if frame_fn is None:
            raise HTTPException(404, "카메라 없음")

        async def frames():
            while True:
                frame = await run_in_threadpool(frame_fn)
                if frame is not None:
                    yield mjpeg_chunk(frame, controller.last_boxes)
                await asyncio.sleep(STREAM_INTERVAL_S)

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    static = Path(static_dir)
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app
