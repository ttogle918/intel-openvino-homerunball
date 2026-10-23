"""A단계 개수 세기: counter 체인. 프레임은 RGB uint8 HxWx3.
비어 있으면 controller가 B단계(시작 개수 + 그리퍼 판정)로 동작한다."""
import logging
import re
import time
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
    """오란다(황갈색 뭉치)를 색 + 위치 + 크기로 센다. 프레임은 RGB. 현장 튜닝 v2 (2026-10-23).
    1) HSV 범위 마스크를 ROI(검은 매트 영역) 안에서만 만든다 → 열기 3x3, 닫기 7x7, 바깥 윤곽, 150px 미만은 무시.
    2) 매트 위 판정(어두운 고리): 덩어리를 ring px 넓힌 고리에서 V < dark_v 인 픽셀이 ring_dark 이상이어야 한다.
       흰 트레이 안의 과자, 흰 로봇·책상 위 덩어리를 거른다 (ring_dark=0이면 끈다).
    3) 오란다 규칙: 매트 위 + 면적 >= min_area + 평균 색상(0..180) <= max_hue. 노란 동그란 과자(색상 23~25)와
       작은 버섯 과자(300~600px)가 빠진다. 붙어 있는 오란다는 한 덩어리가 되므로 round(면적 / unit_area)개로 센다.
    roi: [x1, y1, x2, y2] 가로·세로 비율 (0..1). 없으면 프레임 전체. max_area는 예전 설정 호환용으로만 받는다."""
    name = "opencv"
    MIN_BLOB = 150

    def __init__(self, min_area=800, max_area=None, hsv_low=(5, 60, 90), hsv_high=(40, 255, 255),
                 roi=None, unit_area=1700, max_hue=22.0, ring=12, ring_dark=0.6, dark_v=80):
        self.min_area, self.max_area = min_area, max_area
        self.low, self.high = np.array(hsv_low, np.uint8), np.array(hsv_high, np.uint8)
        if roi is not None and (len(roi) != 4 or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1)):
            raise ValueError(f"roi는 [x1, y1, x2, y2] 비율(0..1, x1<x2, y1<y2)이어야 해요: {roi}")
        self.roi = None if roi is None else tuple(float(v) for v in roi)
        self.unit_area, self.max_hue = float(unit_area), float(max_hue)
        self.ring, self.ring_dark, self.dark_v = int(ring), float(ring_dark), int(dark_v)

    def blobs(self, frame):
        """덩어리마다 {box, area, hue, ring_dark, on_mat, oranda, n}. 튜닝 확인용으로도 쓴다."""
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, self.low, self.high)
        if self.roi is not None:
            x1, y1, x2, y2 = round(self.roi[0] * w), round(self.roi[1] * h), round(self.roi[2] * w), round(self.roi[3] * h)
            keep = np.zeros_like(mask)
            keep[y1:y2, x1:x2] = 255
            mask = cv2.bitwise_and(mask, keep)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        dark = hsv[..., 2] < self.dark_v
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        k = np.ones((2 * self.ring + 1,) * 2, np.uint8)
        out = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < self.MIN_BLOB:
                continue
            blob = np.zeros(mask.shape, np.uint8)
            cv2.drawContours(blob, [c], -1, 255, -1)
            ring = (cv2.dilate(blob, k) > 0) & (blob == 0)
            frac = float(dark[ring].mean()) if ring.any() else 0.0
            hue = float(hsv[..., 0][blob > 0].mean())
            on_mat = frac >= self.ring_dark
            oranda = on_mat and area >= self.min_area and hue <= self.max_hue
            x, y, bw, bh = cv2.boundingRect(c)
            out.append({"box": [x, y, x + bw, y + bh], "area": area, "hue": hue, "ring_dark": frac,
                        "on_mat": on_mat, "oranda": oranda,
                        "n": max(1, round(area / self.unit_area)) if oranda else 0})
        return out

    def count(self, frame):
        counted = [b for b in self.blobs(frame) if b["oranda"]]
        return Count(sum(b["n"] for b in counted), "opencv", [b["box"] for b in counted])


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

    @property
    def names(self):
        return [c.name for c in self.counters]

    def count(self, frame, only=None):
        """체인 순서대로 시도해 첫 결과를 돌려준다. only=이름이면 그 counter 하나만 (없는 이름이면 None)."""
        for c in self.counters:
            if only is not None and c.name != only:
                continue
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
                                                 ("min_area", "max_area", "hsv_low", "hsv_high", "roi", "unit_area",
                                                  "max_hue", "ring", "ring_dark", "dark_v") if k in e}))
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
    p.add_argument("--blobs", action="store_true", help="OpenCV 덩어리별 면적·색상·매트 판정을 보여준다 (ROI·min_area 조정용)")
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
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    for c in v.counters:   # 체인의 counter마다 따로 세어 방법별 결과를 비교한다
        t0 = time.monotonic()
        r = v.count(rgb, only=c.name)
        ms = int((time.monotonic() - t0) * 1000)
        print(f"{c.name}: {'실패' if r is None else f'{r.n}개'} ({ms}ms)", f"boxes={r.boxes}" if r and r.boxes else "")
        if isinstance(c, OpenCVCounter) and a.blobs:
            for b in c.blobs(rgb):
                print("  ", {k: (round(x, 2) if isinstance(x, float) else x) for k, x in b.items()})
    print("체인 결과:", v.count(rgb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
