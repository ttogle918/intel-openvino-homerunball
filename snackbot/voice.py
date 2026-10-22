"""TTS. speak()는 바로 반환하고 백그라운드 스레드가 순서대로 읽는다. 실패해도 예외를 내지 않는다."""
import base64
import io
import logging
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
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


class Voice:
    """options = config의 voice 항목. engine: openai/gemini면 providers[options.provider]와 env의 키를 쓴다."""

    def __init__(self, engine="none", options=None, providers=None, env=None, transport=None):
        self.options = dict(options or {})
        self._http = None
        self.engine_name = engine
        if engine in ("openai", "gemini"):
            try:
                self._http = self._open_http(providers, env, transport)
            except Exception as e:
                log.warning("TTS %s 사용 불가, 소리 없이 진행: %s", engine, e)
                engine = "none"
        self.engine = engine
        self._q = queue.Queue()
        self._tts = None
        self._thread = threading.Thread(target=self._worker, name="voice", daemon=True)
        self._thread.start()

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

    def speak(self, text):
        self._q.put(text)

    def close(self):
        self._q.put(None)
        self._thread.join(timeout=2)
        if self._http is not None:
            self._http.close()

    def _worker(self):
        while True:
            text = self._q.get()
            if text is None:
                return
            try:
                self._say(text)
            except Exception:
                log.exception("TTS 실패")

    def _say(self, text):
        if self.engine == "log":
            print(f"[TTS] {text}", flush=True)
        elif self.engine == "pyttsx3":
            if self._tts is None:
                import pyttsx3
                self._tts = pyttsx3.init()
            try:
                self._tts.say(text)
                self._tts.runAndWait()
            except Exception:
                # 다음 대사에서 엔진을 다시 만든다 (로그는 _worker가 한 번만 남긴다)
                self._tts = None
                raise
        elif self.engine in ("openai", "gemini"):
            play_wav(self.synthesize(text))
        elif self.engine != "none":
            raise ValueError(f"알 수 없는 TTS 엔진: {self.engine}")


def make_voice(cfg, env):
    """config 전체와 env로 Voice를 만든다."""
    opts = cfg.get("voice") or {}
    return Voice(opts.get("engine", "none"), opts, cfg.get("providers"), env)
