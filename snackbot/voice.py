"""TTS. speak()는 바로 반환하고 백그라운드 스레드가 순서대로 읽는다. 실패해도 예외를 내지 않는다."""
import logging
import queue
import threading

log = logging.getLogger(__name__)


class Voice:
    def __init__(self, engine="none"):
        self.engine = engine
        self._q = queue.Queue()
        self._tts = None
        self._thread = threading.Thread(target=self._worker, name="voice", daemon=True)
        self._thread.start()

    def speak(self, text):
        self._q.put(text)

    def close(self):
        self._q.put(None)
        self._thread.join(timeout=2)

    def _worker(self):
        while True:
            text = self._q.get()
            if text is None:
                return
            try:
                self._say(text)
            except Exception as e:
                log.warning("TTS 실패: %s", e)

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
        elif self.engine != "none":
            raise ValueError(f"알 수 없는 TTS 엔진: {self.engine}")
