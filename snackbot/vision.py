"""A단계 개수 세기: counter 체인. 프레임은 RGB uint8 HxWx3.
비어 있으면 controller가 B단계(시작 개수 + 그리퍼 판정)로 동작한다."""
import logging
import re
from dataclasses import dataclass

import cv2
import numpy as np

from .providers import ProviderError, build_chain

log = logging.getLogger(__name__)
MAX_COUNT = 50


@dataclass
class Count:
    n: int
    method: str
    boxes: list | None = None


def parse_count(text):
    m = re.search(r"\d+", text or "")
    if not m:
        return None
    n = int(m.group(0))
    return n if n <= MAX_COUNT else None


def encode_jpeg(frame_rgb, quality=85):
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR),
                           [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG 인코딩 실패")
    return buf.tobytes()


class FakeCounter:
    """dry-run 전용: 가짜 트레이의 개수를 그대로 돌려준다."""
    name = "fake"

    def __init__(self, remaining_fn):
        self.remaining_fn = remaining_fn

    def count(self, frame):
        return Count(int(self.remaining_fn()), "fake")


class OpenCVCounter:
    """색상(HSV) 범위 + 면적으로 센다. 오란다는 모양이 불규칙해 원형도는 쓰지 않는다."""
    name = "opencv"

    def __init__(self, min_area=800, max_area=8000, hsv_low=(10, 60, 80), hsv_high=(30, 255, 255)):
        self.min_area, self.max_area = min_area, max_area
        self.low, self.high = np.array(hsv_low, np.uint8), np.array(hsv_high, np.uint8)

    def count(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, self.low, self.high)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in contours:
            if self.min_area <= cv2.contourArea(c) <= self.max_area:
                x, y, w, h = cv2.boundingRect(c)
                boxes.append([x, y, x + w, y + h])
        return Count(len(boxes), "opencv", boxes)


class VlmCounter:
    """이미지 + 질문 → 숫자만 파싱. 실패하면 retries번 더 묻고, 그래도 안 되면 None."""
    name = "vlm"

    def __init__(self, chain, prompt, retries=1, max_tokens=64):
        self.chain, self.prompt, self.retries, self.max_tokens = chain, prompt, retries, max_tokens

    def count(self, frame):
        jpg = encode_jpeg(frame)
        for _ in range(self.retries + 1):
            try:
                text, _source = self.chain.complete([{"role": "user", "content": self.prompt}],
                                                    max_tokens=self.max_tokens, image=jpg)
            except ProviderError as e:
                log.warning("VLM 실패: %s", e)
                return None
            n = parse_count(text)
            if n is not None:
                return Count(n, "vlm")
        return None


class YoloCounter:
    """Ultralytics OpenVINO 모델 폴더 (YOLO-World 텍스트 클래스로 내보낸 것 등)."""
    name = "yolo"

    def __init__(self, model_dir, conf=0.35, device="intel:gpu"):
        from ultralytics import YOLO
        self.model = YOLO(str(model_dir), task="detect")
        self.conf, self.device = conf, device

    def count(self, frame):
        res = self.model(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), conf=self.conf,
                         device=self.device, verbose=False)[0]
        boxes = [[float(v) for v in b] for b in res.boxes.xyxy.tolist()]
        return Count(len(boxes), "yolo", boxes)


class Vision:
    def __init__(self, counters):
        self.counters = list(counters)

    @property
    def enabled(self):
        return bool(self.counters)

    def count(self, frame):
        for c in self.counters:
            try:
                r = c.count(frame)
            except Exception as e:
                log.warning("counter %s 실패: %s", c.name, e)
                continue
            if r is not None:
                return r
        return None


def build_vision(vision_cfg, providers_cfg, env, remaining_fn=None):
    counters = []
    for e in (vision_cfg or {}).get("chain") or []:
        kind = e.get("type")
        try:
            if kind == "fake":
                counters.append(FakeCounter(remaining_fn))
            elif kind == "opencv":
                counters.append(OpenCVCounter(**{k: e[k] for k in
                                                 ("min_area", "max_area", "hsv_low", "hsv_high") if k in e}))
            elif kind == "vlm":
                chain = build_chain([e], providers_cfg, env)
                if chain:
                    counters.append(VlmCounter(chain, e["prompt"], e.get("retries", 1), e.get("max_tokens", 64)))
            elif kind == "yolo":
                counters.append(YoloCounter(e["model_dir"], e.get("conf", 0.35), e.get("device", "intel:gpu")))
            else:
                log.warning("알 수 없는 counter: %s (건너뜀)", kind)
        except Exception as ex:
            log.warning("counter %s 준비 실패 (건너뜀): %s", kind, ex)
    return Vision(counters)


def main(argv=None):
    import argparse

    from .config import load_config, load_env

    p = argparse.ArgumentParser(prog="python -m snackbot.vision")
    p.add_argument("image")
    p.add_argument("--config", default="config.yaml")
    a = p.parse_args(argv)
    cfg = load_config(a.config)
    v = build_vision(cfg["vision"], cfg.get("providers", {}), load_env())
    if not v.enabled:
        print("vision.chain이 비어 있어요 (B단계). config.yaml에 counter를 추가하세요.")
        return 1
    bgr = cv2.imread(a.image)
    if bgr is None:
        print(f"이미지를 못 읽었어요: {a.image}")
        return 1
    print(v.count(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
