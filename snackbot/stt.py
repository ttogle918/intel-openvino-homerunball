"""음성 → 텍스트. provider 체인(로컬 Whisper 또는 API)을 쓴다.

단독 실행: python -m snackbot.stt a.wav [b.wav ...]  (체인을 만들고 워밍업한 뒤 파일마다 전사)
"""
import logging
import time

from .providers import build_chain

log = logging.getLogger(__name__)


class STT:
    def __init__(self, chain):
        self.chain = chain

    def transcribe(self, wav):
        text, _source = self.chain.transcribe(wav)
        return text

    def warmup(self):
        """warmup이 있는 provider를 미리 로드한다. 실패해도 예외를 내지 않는다."""
        for m in self.chain.members:
            fn = getattr(m.provider, "warmup", None)
            if fn is None:
                continue
            try:
                secs = fn()
                log.info("STT 워밍업 완료: %s (%.1f초)", m.name, secs)
            except Exception as e:
                log.warning("STT 워밍업 실패: %s: %s", m.name, e)


def build_stt(stt_cfg, providers_cfg, env):
    chain = build_chain((stt_cfg or {}).get("chain"), providers_cfg, env)
    return STT(chain) if chain else None


def main(argv=None):
    import argparse
    from pathlib import Path

    from .config import load_config, load_env

    p = argparse.ArgumentParser(prog="python -m snackbot.stt")
    p.add_argument("wavs", nargs="+")
    p.add_argument("--config", default="config.yaml")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(a.config)
    stt = build_stt(cfg.get("stt"), cfg.get("providers", {}), load_env(Path(a.config).resolve().parent / ".env"))
    if stt is None:
        print("stt.chain이 비어 있어요. config.yaml을 확인하세요.")
        return 1
    stt.warmup()
    for path in a.wavs:
        try:
            wav = Path(path).read_bytes()
        except OSError as e:
            print(f"{path}: 파일을 못 읽었어요 · {e}")
            continue
        t0 = time.monotonic()
        try:
            text, source = stt.chain.transcribe(wav)
        except Exception as e:
            print(f"{path}: 실패 · {e}")
            continue
        print(f"{text} · {source} · {(time.monotonic() - t0) * 1000:.0f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
