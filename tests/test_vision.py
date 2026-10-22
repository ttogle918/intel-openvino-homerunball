import cv2
import numpy as np

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
    r = OpenCVCounter(**OPENCV).count(blobs_image())
    assert r.n == 2 and r.method == "opencv" and len(r.boxes) == 2


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
