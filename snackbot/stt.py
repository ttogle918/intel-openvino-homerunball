"""음성 → 텍스트. provider 체인(로컬 Whisper 또는 API)을 쓴다."""
from .providers import build_chain


class STT:
    def __init__(self, chain):
        self.chain = chain

    def transcribe(self, wav):
        text, _source = self.chain.transcribe(wav)
        return text


def build_stt(stt_cfg, providers_cfg, env):
    chain = build_chain((stt_cfg or {}).get("chain"), providers_cfg, env)
    return STT(chain) if chain else None
