"""FastAPI: WebSocket(/ws), 음성(/stt), 카메라(/stream/front), frontend/ 정적 서빙.
controller를 부르기만 한다 (controller는 이 모듈을 모른다). 메시지 형식: docs/UI_DESIGN_PROMPT.md"""
import asyncio
import contextlib
import functools
import json
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

    async def pump(queue):
        """이벤트를 들어온 순서대로 모든 접속의 outbox에 넣는다 (소켓을 await하지 않는다)."""
        while True:
            event = await queue.get()
            for outbox in list(clients):
                outbox.put_nowait((event, True))

    async def writer(ws, outbox, skip_keys):
        """접속별 전송 작업. 오류·타임아웃이면 outbox를 등록 해제하고 소켓을 닫아
        수신 루프를 끝낸다 (브라우저가 close를 받아 재접속한다)."""
        try:
            while True:
                e, live = await outbox.get()
                # 접속 직전 history에 이미 담긴 메시지가 큐에서도 오면 한 번만 보낸다
                key = (e.get("ts"), e.get("role"), e.get("text"))
                if live and e.get("type") == "message" and key in skip_keys:
                    skip_keys.discard(key)      # 한 번만 건너뛴다
                    continue
                await asyncio.wait_for(ws.send_json(e), 2.0)
        except Exception as ex:
            log.debug("ws writer 종료: %r", ex)
        finally:
            clients.discard(outbox)
            with contextlib.suppress(Exception):
                await ws.close()

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
        try:
            yield
        finally:
            shared["loop"] = None
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan)
    controller.subscribe(on_event)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        # 동기 구간(await 없음): 초기 상태를 담고 등록 → 이벤트 누락·중복 없음
        outbox = asyncio.Queue()
        outbox.put_nowait((info, False))
        outbox.put_nowait((controller.snapshot(), False))
        history = list(controller.history)
        for m in history:
            outbox.put_nowait((m, False))
        skip_keys = {(m.get("ts"), m.get("role"), m.get("text")) for m in history}
        clients.add(outbox)
        task = asyncio.create_task(writer(ws, outbox, skip_keys))
        commands = asyncio.Queue()   # 연결별 FIFO: chat/resume/restart 를 들어온 순서대로 하나씩

        async def worker():
            while True:
                fn, args = await commands.get()
                try:
                    await run_in_threadpool(fn, *args)
                except Exception as e:
                    log.warning("ws 명령 처리 실패: %r", e)

        worker_task = asyncio.create_task(worker())

        try:
            while True:
                text = await ws.receive_text()
                try:
                    msg = json.loads(text)
                    kind = msg.get("type")
                    if kind == "chat":
                        commands.put_nowait((controller.chat, (str(msg.get("text", "")), "text")))
                    elif kind == "command" and msg.get("name") == "estop":
                        try:
                            controller.command("estop")     # 즉시 처리: 큐·스레드풀 뒤에 서지 않는다
                        except Exception:
                            log.exception("비상정지 처리 실패")
                    elif kind == "command" and msg.get("name") == "restart":
                        # 접수한 순간의 세션 번호를 함께 넣는다: 대기하는 사이 비상정지가 끼면 이 재시작은 거부된다
                        g = controller.generation()
                        commands.put_nowait((functools.partial(controller.command, "restart", expect_gen=g), ()))
                    elif kind == "command" and msg.get("name") in UI_COMMANDS:
                        commands.put_nowait((controller.command, (msg["name"],)))
                except Exception as e:
                    log.warning("잘못된 ws 메시지 무시: %r (%s)", text[:100], e)
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(outbox)
            task.cancel()
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(task, worker_task, return_exceptions=True)

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
            while not controller.stopped:
                try:
                    frame = await run_in_threadpool(frame_fn)
                    chunk = mjpeg_chunk(frame, controller.last_boxes) if frame is not None else None
                except Exception as e:
                    log.debug("프레임 오류, 건너뜀: %r", e)
                    chunk = None
                if chunk is not None:
                    yield chunk
                await asyncio.sleep(STREAM_INTERVAL_S)

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    static = Path(static_dir)
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app
