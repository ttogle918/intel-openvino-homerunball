import json

from conftest import FirstRng
from snackbot.brain import (
    Brain, allowed_intents, allowed_skills, keyword_intent, parse_json, parse_n,
)
from snackbot.providers import Chain, Member, ProviderError

D = {"safe_max": 3, "force_refuse": 6, "max_retry": 2}


class Scripted:
    def __init__(self, *replies):
        self.replies, self.messages = list(replies), None

    def complete(self, messages, max_tokens=300, image=None):
        self.messages = messages
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(cfg, *replies):
    chain = Chain([Member("fake", Scripted(*replies))]) if replies else None
    return Brain(cfg, chain=chain, rng=FirstRng())


def test_guard_table():
    assert allowed_skills(0, 0, D) == ["done"]
    assert allowed_skills(0, 9, D) == ["done"]
    assert allowed_skills(3, 3, D) == ["oranda_pickup"]
    assert allowed_skills(3, 4, D) == ["oranda_pickup", "dori_dori"]
    assert allowed_skills(3, 5, D) == ["oranda_pickup", "dori_dori"]
    assert allowed_skills(3, 6, D) == ["dori_dori"]


def test_rules_only_decide_uses_guard_and_lines(cfg):
    b = make(cfg)
    d = b.decide(2, 0, "WORKING")
    assert d["skill"] == "oranda_pickup" and d["source"] == "rules"
    assert d["say"] in ("오란다 하나 옮길게요!", "이번 것도 제가 할게요.")
    assert b.decide(2, 3, "WORKING")["say"] in ("으… 팔이 조금 뻐근한데요.", "이거 몇 개 남았어요?")
    assert b.decide(2, 7, "WORKING")["skill"] == "dori_dori"
    assert b.decide(0, 1, "WORKING")["skill"] == "done"


def test_llm_choice_used_in_free_zone(cfg):
    d = make(cfg, '{"skill": "dori_dori", "say": "싫어요!"}').decide(2, 4, "WORKING")
    assert d == {"skill": "dori_dori", "say": "싫어요!", "source": "fake"}


def test_guard_overrides_llm_but_keeps_say(cfg):
    d = make(cfg, '좋아요 {"skill": "dori_dori", "say": "쉬고 싶어요"}').decide(2, 1, "WORKING")
    assert d["skill"] == "oranda_pickup" and d["say"] == "쉬고 싶어요"


def test_bad_json_or_unknown_skill_falls_back_to_rules(cfg):
    for reply in ["no json here", '{"skill": "dance", "say": "춤!"}']:
        d = make(cfg, reply).decide(2, 1, "WORKING")
        assert d["skill"] == "oranda_pickup" and d["source"] == "rules"
        assert d["say"] != "춤!"


def test_long_or_empty_say_replaced(cfg):
    long = "가" * 81
    d = make(cfg, json.dumps({"skill": "oranda_pickup", "say": long}, ensure_ascii=False)).decide(2, 1, "WORKING")
    assert d["say"] != long and 0 < len(d["say"]) <= 80
    assert make(cfg, '{"skill": "oranda_pickup", "say": ""}').decide(2, 1, "WORKING")["say"]


def test_provider_error_falls_back(cfg):
    d = make(cfg, ProviderError("down")).decide(2, 1, "WORKING")
    assert d["source"] == "rules" and d["skill"] == "oranda_pickup"


def test_decide_prompt_has_target_and_allowed(cfg):
    fake = Scripted('{"skill": "oranda_pickup", "say": "네"}')
    Brain(cfg, chain=Chain([Member("f", fake)]), rng=FirstRng()).decide(2, 4, "WORKING")
    assert fake.messages[0]["role"] == "system" and "오란다" in fake.messages[0]["content"]
    assert json.loads(fake.messages[1]["content"])["allowed"] == ["oranda_pickup", "dori_dori"]


def test_parse_json():
    assert parse_json('앞말 {"a": 1} 뒷말') == {"a": 1}
    assert parse_json("[1, 2]") is None
    assert parse_json("{broken") is None


def test_allowed_intents():
    assert allowed_intents("IDLE") == ["start_task", "chat"]
    assert allowed_intents("DONE") == ["start_task", "chat"]
    assert allowed_intents("REFUSING") == ["resume", "chat"]
    assert allowed_intents("WORKING") == ["chat"]
    assert allowed_intents("ESTOP") == ["chat"]


def test_keyword_intent():
    assert keyword_intent("오란다 옮겨줘", ["start_task", "chat"]) == "start_task"
    assert keyword_intent("안녕", ["start_task", "chat"]) == "chat"
    assert keyword_intent("조금만 더 해줘", ["resume", "chat"]) == "resume"
    assert keyword_intent("옮겨줘", ["resume", "chat"]) == "chat"
    assert keyword_intent("옮겨줘", ["chat"]) == "chat"


def test_parse_n():
    assert parse_n("3개 옮겨줘") == 3
    assert parse_n("오란다 두 개만") == 2
    assert parse_n("다섯개") == 5
    assert parse_n("네, 옮겨줘") is None
    assert parse_n("과자 옮겨줘") is None
    assert parse_n("100개") is None


def test_chat_rules(cfg):
    b = make(cfg)
    r = b.chat("오란다 3개 옮겨줘", "IDLE", 0)
    assert r["intent"] == "start_task" and r["n"] == 3 and r["source"] == "rules"
    assert b.chat("안녕", "IDLE", 0)["intent"] == "chat"
    assert b.chat("안녕", "IDLE", 0)["n"] is None
    assert b.chat("조금만 더 해줘", "REFUSING", 6)["intent"] == "resume"
    assert b.chat("옮겨줘", "WORKING", 1)["say"] == "지금 일하는 중이에요! 이따 얘기해요."


def test_chat_llm_valid(cfg):
    r = make(cfg, '{"intent": "start_task", "say": "출발!", "n": 2}').chat("일 좀 해", "IDLE", 0)
    assert r == {"intent": "start_task", "say": "출발!", "n": 2, "source": "fake"}


def test_chat_llm_intent_outside_allowed_uses_keywords(cfg):
    r = make(cfg, '{"intent": "start_task", "say": "가요!", "n": 2}').chat("부탁해", "REFUSING", 6)
    assert r["intent"] == "resume" and r["say"] == "가요!" and r["n"] is None


def test_chat_llm_bad_n_falls_back_to_text(cfg):
    r = make(cfg, '{"intent": "start_task", "say": "네", "n": "many"}').chat("4개 옮겨", "IDLE", 0)
    assert r["n"] == 4


def test_chat_in_estop_uses_estop_line(cfg):
    b = make(cfg)
    r = b.chat("안녕", "ESTOP", 2)
    assert r["intent"] == "chat" and "비상정지" in r["say"]
