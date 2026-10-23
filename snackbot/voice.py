"""TTS. speak()는 바로 반환하고 백그라운드 스레드가 순서대로 읽는다. 실패해도 예외를 내지 않는다."""
import base64
import contextlib
import io
import logging
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
import os

import httpx

log = logging.getLogger(__name__)


PLAYERS = (["aplay", "-q"], ["paplay"], ["afplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"])


def play_wav(data):
    """WAV bytes를 재생하고 끝날 때까지 기다린다 (voice 스레드에서만 부른다)."""
    if sys.platform == "win32":
        import winsound
        winsound.PlaySound(data, winsound.SND_MEMORY)
        return
    for cmd in PLAYERS:
        exe = shutil.which(cmd[0])
        if not exe:
            continue
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            subprocess.run([exe, *cmd[1:], path], check=True, timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            os.unlink(path)
        return
    raise RuntimeError("WAV 재생기가 없음 (aplay, paplay, afplay, ffplay)")


def pcm_to_wav(pcm, rate=24000):
    """16bit 모노 PCM을 WAV bytes로 감싼다."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


# Windows 내장 음성(SAPI)으로 WAV 파일 만들기. 문장·목소리·경로는 환경 변수로 넘긴다 (따옴표 이스케이프 문제 없음)
_SAPI_SCRIPT = (
    "$ErrorActionPreference='Stop'; "   # 목소리·속도 설정 실패를 조용히 넘기지 않고 오류로 만든다
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "if ($env:SNACKBOT_TTS_VOICE) { $s.SelectVoice($env:SNACKBOT_TTS_VOICE) }; "
    "$s.Rate = [int]$env:SNACKBOT_TTS_RATE; "
    "$s.SetOutputToWaveFile($env:SNACKBOT_TTS_OUT); "
    "$s.Speak($env:SNACKBOT_TTS_TEXT); $s.Dispose()"
)
QUOTA_STATUS = (402, 403, 429)   # 크레딧·권한·한도: 잠시 예비 음성만 쓴다


class Voice:
    """options = config의 voice 항목. engine: openai/gemini면 providers[options.provider]와 env의 키를 쓴다.
    options.fallback: windows 이면 API 합성이 실패할 때 Windows 내장 음성(fallback_voice)으로 대신 말한다."""

    def __init__(self, engine="none", options=None, providers=None, env=None, transport=None):
        self.options = dict(options or {})
        self._http = None
        self.engine_name = engine
        self.fallback = self.options.get("fallback") if sys.platform == "win32" else None
        self._primary_off_until = 0.0   # 한도 오류 뒤 이 시각까지는 API를 건너뛰고 예비 음성
        if engine in ("openai", "gemini"):
            try:
                self._http = self._open_http(providers, env, transport)
            except Exception as e:
                if self.fallback == "windows":
                    log.warning("TTS %s 사용 불가, Windows 예비 음성으로: %s", engine, e)
                    engine = "windows"
                else:
                    log.warning("TTS %s 사용 불가, 소리 없이 진행: %s", engine, e)
                    engine = "none"
        self.engine = engine
        self._q = queue.Queue()
        self._closed = False
        self._close_lock = threading.Lock()
        self._tts = None
        self._pq = queue.Queue(maxsize=2)  # 합성이 끝난 (wav, text, event): 재생 스레드가 가져간다
        self._join_timeout_s = 2  # close()가 두 스레드를 기다리는 전체 상한 (나눠 쓰지 않고 하나의 마감 시간)
        self._abandon = threading.Event()  # close()의 마감 시간이 지난 뒤: 남은 문장은 재생하지 않고 Event만 set 한다
        self._epoch = 0  # clear_pending()마다 올라간다: 이전 epoch의 문장은 재생하지 않는다
        self._synth_thread = threading.Thread(target=self._synth_worker, name="voice-synth", daemon=True)
        self._play_thread = threading.Thread(target=self._play_worker, name="voice-play", daemon=True)
        self._synth_thread.start()
        self._play_thread.start()

    def _open_http(self, providers, env, transport):
        o = self.options
        pc = (providers or {}).get(o.get("provider"))
        if not pc or not o.get("model") or not o.get("voice"):
            raise ValueError("voice.provider/model/voice 설정이 필요")
        key = (env or {}).get(pc.get("api_key_env", ""), "")
        if not key:
            raise ValueError(f"{pc.get('api_key_env')} 없음")
        timeout = float(o.get("timeout_s", 15))
        if self.engine_name == "gemini":  # 네이티브 API: 키는 헤더로만 보낸다
            base = pc.get("native_base_url") or pc["base_url"].rstrip("/").removesuffix("/openai")
            return httpx.Client(base_url=base.rstrip("/"), headers={"x-goog-api-key": key},
                                timeout=timeout, transport=transport)
        return httpx.Client(base_url=pc["base_url"].rstrip("/"), headers={"Authorization": f"Bearer {key}"},
                            timeout=timeout, transport=transport)

    def synthesize(self, text):
        if self.engine == "gemini":
            return self._synthesize_gemini(text)
        body = {"model": self.options["model"], "voice": self.options["voice"],
                "input": text, "response_format": "wav"}
        if self.options.get("instructions"):
            body["instructions"] = self.options["instructions"]
        r = self._http.post("/audio/speech", json=body)
        r.raise_for_status()
        return r.content

    def _synthesize_gemini(self, text):
        o = self.options
        prompt = f"{o['instructions']} {text}" if o.get("instructions") else text
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["AUDIO"],
                                     "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                                         "voiceName": o["voice"]}}}}}
        r = self._http.post(f"/models/{o['model']}:generateContent", json=body)
        r.raise_for_status()
        inline = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
        m = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
        return pcm_to_wav(base64.b64decode(inline["data"]), int(m.group(1)) if m else 24000)

    def _synthesize_windows(self, text):
        """Windows 내장 음성(SAPI)으로 WAV bytes. Windows가 아니면 RuntimeError."""
        if sys.platform != "win32":
            raise RuntimeError("Windows 예비 음성은 Windows에서만 된다")
        o = self.options
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            env = {**os.environ, "SNACKBOT_TTS_TEXT": text, "SNACKBOT_TTS_OUT": path,
                   "SNACKBOT_TTS_VOICE": str(o.get("fallback_voice", "Microsoft Heami Desktop")),
                   "SNACKBOT_TTS_RATE": str(int(o.get("fallback_rate", 0)))}
            try:
                subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _SAPI_SCRIPT],
                               env=env, check=True, timeout=float(o.get("fallback_timeout_s", 15)),
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                err = (e.stderr or b"")
                err = err.decode("utf-8", "replace") if isinstance(err, bytes) else str(err)
                log.warning("Windows 예비 음성 실패 (종료 코드 %s): %s", e.returncode, err.strip()[:300])
                raise
            with open(path, "rb") as f:
                return f.read()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)

    def _synthesize_any(self, text):
        """API 합성 → 실패하면 (fallback 설정 시) Windows 예비 음성. 한도 오류 뒤에는 잠시 API를 건너뛴다."""
        if self.engine == "windows":
            return self._synthesize_windows(text)
        now = time.monotonic()
        if now >= self._primary_off_until:
            try:
                return self.synthesize(text)
            except Exception as e:
                if self.fallback != "windows":
                    raise
                status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
                if status in QUOTA_STATUS:
                    cooldown = float(self.options.get("fallback_cooldown_s", 600))
                    self._primary_off_until = now + cooldown
                    log.warning("TTS %s 한도·권한 오류(%s): %d초 동안 Windows 예비 음성", self.engine, status, cooldown)
                else:
                    # 시간 초과·연결 오류: 문장마다 timeout_s를 기다리지 않게 짧게 API를 건너뛴다
                    cooldown = float(self.options.get("fallback_error_cooldown_s", 60))
                    self._primary_off_until = now + cooldown
                    log.warning("TTS %s 실패, %d초 동안 Windows 예비 음성: %s", self.engine, cooldown, e)
        return self._synthesize_windows(text)

    def speak(self, text):
        """대기열에 넣고 Event를 반환한다. 이벤트는 재생 직전(실패·종료 시에도 반드시) set 된다."""
        started = threading.Event()
        with self._close_lock:
            if self._closed:
                started.set()
            else:
                self._q.put((text, started, self._epoch))
        return started

    def clear_pending(self):
        """아직 재생을 시작하지 않은 문장(합성 대기·재생 대기)을 버리고 각 Event를 set 한다.
        지금 재생 중인 한 문장은 끝까지 나간다. 합성 중이던 문장도 epoch 확인으로 버려진다."""
        with self._close_lock:
            self._epoch += 1
            self._drain(self._q)
            self._drain(self._pq)

    @staticmethod
    def _drain(q):
        """대기열을 비우며 항목의 Event를 set 한다. 종료 신호(None)는 되돌려 둔다."""
        sentinel = False
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                sentinel = True
            else:
                item[-2].set()
        if sentinel:
            q.put_nowait(None)

    def close(self):
        with self._close_lock:
            self._closed = True
            self._q.put(None)
        deadline = time.monotonic() + self._join_timeout_s
        for t in (self._synth_thread, self._play_thread):
            t.join(timeout=max(0.0, deadline - time.monotonic()))
        # 처리되지 못하고 남은 문장: 기다리는 쪽이 막히지 않게 set. 종료 신호는 되돌려 둔다.
        # 포기 표시와 비우기를 락 안에서: 합성 스레드의 put(같은 락)이 비우기 뒤에 끼어들지 못한다.
        with self._close_lock:
            self._abandon.set()  # 아직 도는 스레드가 손에 든 문장도 재생 대신 set 하게 한다
            self._drain(self._q)
            self._drain(self._pq)
            with contextlib.suppress(queue.Full):
                self._pq.put_nowait(None)  # 재생 스레드가 남지 않게 종료 신호 (비운 뒤라 들어간다)
        if self._http is not None:
            self._http.close()

    def _synth_worker(self):
        """합성 스레드: 앞 문장이 재생되는 동안 다음 문장을 미리 합성한다."""
        while True:
            item = self._q.get()
            if item is None:
                self._put_play(None)
                return
            text, started, epoch = item
            wav = None
            if epoch != self._epoch:  # 비상정지 등으로 비워진 뒤에 손에 든 문장
                started.set()
                continue
            if self.engine in ("openai", "gemini", "windows"):
                try:
                    wav = self._synthesize_any(text)
                except Exception:
                    log.exception("TTS 합성 실패")
                    started.set()
                    continue
            if not self._put_play((wav, text, started, epoch)):
                started.set()  # 닫히는 중이라 넘기지 못했다: 기다리는 쪽이 막히지 않게

    def _put_play(self, item):
        """재생 큐에 넣는다. 가득 차 있으면 기다리되, close()가 포기하면 False."""
        while True:
            with self._close_lock:
                if self._abandon.is_set():
                    return False
                if item is not None and item[-1] != self._epoch:  # clear_pending 뒤: 넘기지 않고 버린다
                    return False
                try:
                    self._pq.put_nowait(item)
                    return True
                except queue.Full:
                    pass
            self._abandon.wait(0.05)

    def _play_worker(self):
        while True:
            item = self._pq.get()
            if item is None:
                return
            wav, text, started, epoch = item
            if self._abandon.is_set() or epoch != self._epoch:  # 포기된 뒤·비워진 뒤에는 재생하지 않고 set만
                started.set()
                continue
            try:
                self._say(text, started, wav)
            except Exception:
                log.exception("TTS 실패")
            finally:
                started.set()

    def _say(self, text, started=None, wav=None):
        """재생. started는 소리가 나기 직전에 set 한다 (실패하면 호출한 쪽 finally가 set)."""
        def go():
            if started is not None:
                started.set()

        if self.engine == "log":
            go()
            print(f"[TTS] {text}", flush=True)
        elif self.engine == "pyttsx3":
            if self._tts is None:
                import pyttsx3
                self._tts = pyttsx3.init()
            try:
                go()
                self._tts.say(text)
                self._tts.runAndWait()
            except Exception:
                # 다음 대사에서 엔진을 다시 만든다 (로그는 호출한 쪽이 한 번만 남긴다)
                self._tts = None
                raise
        elif self.engine in ("openai", "gemini", "windows"):
            go()
            play_wav(wav)
        elif self.engine != "none":
            raise ValueError(f"알 수 없는 TTS 엔진: {self.engine}")


def make_voice(cfg, env):
    """config 전체와 env로 Voice를 만든다."""
    opts = cfg.get("voice") or {}
    return Voice(opts.get("engine", "none"), opts, cfg.get("providers"), env)
