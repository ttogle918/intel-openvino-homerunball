"""FastAPI: WebSocket(/ws), 음성(/stt), 카메라(/stream/front, /stream/{cam}), 재생 데이터(/api/replay/{skill}, /replays),
frontend/ 정적 서빙. controller를 부르기만 한다 (controller는 이 모듈을 모른다).
메시지 형식: docs/UI_DESIGN_PROMPT.md, 4분할·3D: docs/superpowers/specs/2026-10-22-digital-twin-design.md"""
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

from .twin import replay_payload, to_radians
from .vision import encode_jpeg

log = logging.getLogger(__name__)
UI_COMMANDS = ("resume", "estop", "restart")
STREAM_INTERVAL_S = 0.1
MJPEG = "multipart/x-mixed-replace; boundary=frame"


def draw_boxes(frame, boxes):
    if not boxes:
        return frame
    out = frame.copy()
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), (255, 200, 0), 2)
    return out


def mjpeg_chunk(frame, boxes=None):
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encode_jpeg(draw_boxes(frame, boxes)) + b"\r\n"


def create_app(controller, info, frame_fn=None, stt=None, static_dir="frontend", *, cameras=(), box_camera=None,
               joints_fn=None, joints_hz=15.0, convert=None, replays_dir=None):
    """frame_fn(cam=None): RGB 프레임. 인자 없이 부르면 vision 카메라 (/stream/front).
    cameras: /stream/{cam}으로 열 수 있는 config 카메라 이름. box_camera: 개수 세기 상자를 그릴 카메라.
    joints_fn(): normalized 관절값 6개 또는 None (dry-run). joints_hz마다 읽어 바뀌면 joints 메시지.
    convert: normalized → 라디안 (기본 twin.to_radians). replays_dir: /api/replay, /replays의 폴더."""
    clients = set()
    shared = {"loop": None, "queue": None, "joints": None}
    camera_names = set(cameras)
    to_rad = convert or to_radians

    async def pump(queue):
        """이벤트를 들어온 순서대로 모든 접속의 outbox에 넣는다 (소켓을 await하지 않는다)."""
        while True:
            event = await queue.get()
            for outbox in list(clients):
                outbox.put_nowait((event, True))

    async def joints_pump():
        """joints_fn()을 joints_hz로 읽어 라디안으로 바꾸고, 값이 바뀌었을 때만 모든 연결에 보낸다."""
        last = None
        while True:
            try:
                values = joints_fn()
                q = None if values is None else [round(float(v), 4) for v in to_rad(values)]
            except Exception as e:
                log.debug("관절값 읽기 실패: %r", e)
                q = None
            if q is not None and q != last:
                last = q
                event = {"type": "joints", "q": q}
                shared["joints"] = event
                shared["queue"].put_nowait(event)
            await asyncio.sleep(1.0 / joints_hz)

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
        tasks = [asyncio.create_task(pump(shared["queue"]))]
        if joints_fn is not None:
            tasks.append(asyncio.create_task(joints_pump()))
        try:
            yield
        finally:
            shared["loop"] = None
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

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
        if shared["joints"] is not None:   # 팔이 멈춰 있으면 다음 joints가 오지 않으므로 마지막 값을 한 번
            outbox.put_nowait((shared["joints"], False))
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

    async def mjpeg(read, boxes):
        while not controller.stopped:
            try:
                frame = await run_in_threadpool(read)
                chunk = mjpeg_chunk(frame, boxes()) if frame is not None else None
            except Exception as e:
                log.debug("프레임 오류, 건너뜀: %r", e)
                chunk = None
            if chunk is not None:
                yield chunk
            await asyncio.sleep(STREAM_INTERVAL_S)

    @app.get("/stream/front")
    async def stream_front():
        if frame_fn is None:
            raise HTTPException(404, "카메라 없음")
        return StreamingResponse(mjpeg(frame_fn, lambda: controller.last_boxes), media_type=MJPEG)

    @app.get("/stream/{cam}")
    async def stream_cam(cam: str):
        if frame_fn is None or cam not in camera_names:
            raise HTTPException(404, "카메라 없음")
        boxes = (lambda: controller.last_boxes) if cam == box_camera else (lambda: None)
        return StreamingResponse(mjpeg(functools.partial(frame_fn, cam), boxes), media_type=MJPEG)

    @app.get("/api/replay/{skill}")
    async def replay(skill: str):
        data = None
        if replays_dir is not None:
            data = await run_in_threadpool(replay_payload, replays_dir, skill, to_rad)
        if data is None:
            raise HTTPException(404, f"{skill} 재생 데이터 없음")
        return data

    if replays_dir is not None:
        Path(replays_dir).mkdir(parents=True, exist_ok=True)
        app.mount("/replays", StaticFiles(directory=replays_dir), name="replays")
    static = Path(static_dir)
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app
