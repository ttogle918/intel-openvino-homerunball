from pathlib import Path

import cv2
import numpy as np
import pytest

from snackbot.providers import Chain, Member
from snackbot.vision import (
    Count, FakeCounter, OpenCVCounter, Vision, VlmCounter, build_vision, encode_jpeg, parse_count,
)

OPENCV = dict(min_area=800, max_area=8000, hsv_low=[10, 60, 80], hsv_high=[30, 255, 255])


def blobs_image():
    img = np.full((240, 320, 3), 255, np.uint8)            # RGB
    cv2.circle(img, (60, 60), 25, (200, 120, 40), -1)      # 황갈색 → 셈
    cv2.circle(img, (200, 120), 25, (200, 120, 40), -1)    # 황갈색 → 셈
    cv2.circle(img, (280, 200), 4, (200, 120, 40), -1)     # 너무 작음
    cv2.circle(img, (120, 180), 25, (40, 80, 220), -1)     # 파란색
    return img


class Scripted:
    def __init__(self, *replies):
        self.replies, self.images = list(replies), []

    def complete(self, messages, max_tokens=300, image=None):
        self.images.append(image)
        return self.replies.pop(0)


class Boom:
    name = "boom"

    def count(self, frame):
        raise RuntimeError("x")


class Nothing:
    name = "nothing"

    def count(self, frame):
        return None


def test_opencv_counter_counts_brown_blobs_in_size_range():
    img = blobs_image()
    img[(img == 255).all(axis=2)] = 20                       # 검은 매트 위가 아니면 세지 않는다 (v2)
    r = OpenCVCounter(**OPENCV).count(img)
    assert r.n == 2 and r.method == "opencv" and len(r.boxes) == 2


def test_opencv_ignores_blobs_not_on_dark_mat_unless_ring_check_off():
    assert OpenCVCounter(**OPENCV).count(blobs_image()).n == 0           # 흰 바탕 (트레이·로봇 위)
    assert OpenCVCounter(**OPENCV, ring_dark=0).count(blobs_image()).n == 2


def mat(w=400, h=300):
    return np.full((h, w, 3), 20, np.uint8)


def test_opencv_roi_hue_and_merge_rules():
    img = mat()
    cv2.circle(img, (100, 100), 26, (200, 120, 40), -1)        # 오란다
    cv2.circle(img, (300, 100), 26, (200, 120, 40), -1)        # 오른쪽 절반 (ROI 밖일 때)
    cv2.circle(img, (100, 220), 26, (200, 190, 40), -1)        # 노란 과자 (색상이 max_hue보다 큼)
    cv2.circle(img, (200, 220), 10, (200, 120, 40), -1)        # min_area 미만
    kw = dict(min_area=800, unit_area=1700)
    assert OpenCVCounter(**kw).count(img).n == 2
    r = OpenCVCounter(**kw, roi=[0, 0, 0.5, 1]).count(img)
    assert r.n == 1 and len(r.boxes) == 1
    two = mat()
    cv2.ellipse(two, (100, 100), (50, 26), 0, 0, 360, (200, 120, 40), -1)   # 붙은 두 개 = 한 덩어리 약 4000px
    r = OpenCVCounter(**kw).count(two)
    assert r.n == 2 and len(r.boxes) == 1


def test_opencv_roi_validation_and_legacy_kwargs():
    with pytest.raises(ValueError):
        OpenCVCounter(roi=[0.6, 0, 0.5, 1])
    OpenCVCounter(min_area=800, max_area=8000, hsv_low=[10, 60, 80], hsv_high=[30, 255, 255])


SAMPLES = Path(__file__).parent / "samples"
# (파일, ROI 픽셀 x1,y1,x2,y2 @1280x720, min_area, 기대 개수)
FIELD = [("tower_oranda3_data.jpg", (455, 165, 880, 615), 1000, 3),
         ("tower_oranda5_data.jpg", (455, 165, 880, 615), 1000, 5),
         ("tower_oranda1_tray3_data.jpg", (455, 165, 880, 615), 1000, 1),    # 트레이 안 3개는 세지 않는다
         ("tower_oranda3_balls2_live.jpg", (370, 150, 790, 610), 800, 3)]    # 노란 공 2개는 세지 않는다


@pytest.mark.parametrize("name,roi,min_area,expected", FIELD)
def test_opencv_field_samples(name, roi, min_area, expected):
    bgr = cv2.imread(str(SAMPLES / name))
    h, w = bgr.shape[:2]
    c = OpenCVCounter(roi=[roi[0] / w, roi[1] / h, roi[2] / w, roi[3] / h], min_area=min_area, unit_area=1700)
    assert c.count(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).n == expected


def test_vision_only_runs_named_counter():
    v = Vision([FakeCounter(lambda: 1), Nothing()])
    assert v.names == ["fake", "nothing"]
    assert v.count(None, only="fake") == Count(1, "fake")
    assert v.count(None, only="nothing") is None and v.count(None, only="missing") is None


def test_parse_count():
    assert parse_count("3") == 3
    assert parse_count("There are 2 snacks.") == 2
    assert parse_count("none") is None
    assert parse_count("999") is None


def test_vlm_counter_retries_then_gives_up():
    fake = Scripted("잘 모르겠어요", "두 개")
    assert VlmCounter(Chain([Member("f", fake)]), "How many?", retries=1).count(blobs_image()) is None
    assert len(fake.images) == 2


def test_vlm_counter_parses_number_and_sends_jpeg():
    fake = Scripted("음", "4")
    assert VlmCounter(Chain([Member("f", fake)]), "How many?").count(blobs_image()) == Count(4, "vlm")
    assert fake.images[0][:2] == b"\xff\xd8"


def test_vision_chain_falls_through():
    v = Vision([Boom(), Nothing(), FakeCounter(lambda: 2)])
    assert v.enabled and v.count(None) == Count(2, "fake")
    assert Vision([Nothing()]).count(None) is None
    assert not Vision([]).enabled


def test_build_vision_types_and_empty():
    v = build_vision({"chain": [{"type": "fake"}, {"type": "opencv", **OPENCV}, {"type": "mystery"}]},
                     {}, {}, remaining_fn=lambda: 1)
    assert [c.name for c in v.counters] == ["fake", "opencv"]
    assert build_vision({"chain": []}, {}, {}).counters == []


def test_build_vision_skips_vlm_without_key_and_yolo_without_package():
    providers = {"openrouter": {"type": "openai_compat", "base_url": "https://o.test/v1",
                                "api_key_env": "OR_KEY"}}
    v = build_vision({"chain": [
        {"type": "vlm", "provider": "openrouter", "model": "m", "prompt": "How many?"},
        {"type": "yolo", "model_dir": "models/does_not_exist"},
    ]}, providers, {})
    assert v.counters == []


def test_encode_jpeg():
    assert encode_jpeg(blobs_image())[:2] == b"\xff\xd8"
