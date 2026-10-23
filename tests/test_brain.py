import json
import pytest

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
    cfg["decision"]["refuse"] = "fixed"
    b = make(cfg)
    d = b.decide(2, 0, "WORKING")
    assert d["skill"] == "oranda_pickup" and d["source"] == "rules"
    assert d["say"] in ("오란다 하나 옮길게요!", "이번 것도 제가 할게요.")
    assert b.decide(2, 3, "WORKING")["say"] in ("으… 팔이 조금 뻐근한데요.", "이거 몇 개 남았어요?")
    assert b.decide(2, 7, "WORKING")["skill"] == "dori_dori"
    assert b.decide(0, 1, "WORKING")["skill"] == "done"


def test_llm_choice_used_in_free_zone(cfg):
    cfg["decision"]["refuse"] = "fixed"
    d = make(cfg, '{"skill": "dori_dori", "say": "싫어요!"}').decide(2, 4, "WORKING")
    assert d == {"skill": "dori_dori", "say": "싫어요!", "source": "fake"}


def test_guard_overrides_llm_and_discards_its_say(cfg):
    d = make(cfg, '좋아요 {"skill": "dori_dori", "say": "쉬고 싶어요"}').decide(2, 1, "WORKING")
    assert d["skill"] == "oranda_pickup" and d["say"] != "쉬고 싶어요"   # 동작이 바뀌면 대사도 규칙 대사로


def test_guard_overrides_llm_and_discards_its_say_in_half_mode(cfg):
    cfg["decision"]["refuse"] = "half"
    fake = Scripted('{"skill": "oranda_pickup", "say": "옮길게요"}')
    b = Brain(cfg, chain=Chain([Member("f", fake)]), rng=FirstRng())
    d = b.decide(3, 3, "WORKING", total=6)           # 거부 차례: allowed == ["dori_dori"]
    assert d["skill"] == "dori_dori" and d["say"] != "옮길게요"
    system = fake.messages[0]["content"]
    assert "4~5면" not in system and "{rules}" not in system and "하나뿐이면" in system


def test_fixed_prompt_keeps_count_rules(cfg):
    cfg["decision"]["refuse"] = "fixed"
    fake = Scripted('{"skill": "oranda_pickup", "say": "네"}')
    Brain(cfg, chain=Chain([Member("f", fake)]), rng=FirstRng()).decide(2, 4, "WORKING")
    assert "4~5면" in fake.messages[0]["content"] and "{rules}" not in fake.messages[0]["content"]


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
    cfg["decision"]["refuse"] = "fixed"
    fake = Scripted('{"skill": "oranda_pickup", "say": "네"}')
    Brain(cfg, chain=Chain([Member("f", fake)]), rng=FirstRng()).decide(2, 4, "WORKING")
    assert fake.messages[0]["role"] == "system" and "오란다" in fake.messages[0]["content"]
    assert json.loads(fake.messages[1]["content"])["allowed"] == ["oranda_pickup", "dori_dori"]


def test_parse_json():
    assert parse_json('앞말 {"a": 1} 뒷말') == {"a": 1}
    assert parse_json("[1, 2]") is None
    assert parse_json("{broken") is None


def test_allowed_intents():
    assert allowed_intents("IDLE") == ["start_task", "chat", "dori_dori"]
    assert allowed_intents("DONE") == ["start_task", "chat"]
    assert allowed_intents("REFUSING") == ["resume", "chat"]
    assert allowed_intents("WORKING") == ["chat"]
    assert allowed_intents("ESTOP") == ["chat"]
    assert allowed_intents("TESTING") == ["chat"]


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


def test_chat_text_n_wins_over_llm_n(cfg):
    # 문장에서 읽은 개수가 있으면 LLM 값은 무시한다 (횟수는 코드가 정한다)
    r = make(cfg, '{"intent": "start_task", "say": "네", "n": 20}').chat("3개 옮겨줘", "IDLE", 0)
    assert r["n"] == 3


def test_chat_in_estop_uses_estop_line(cfg):
    b = make(cfg)
    r = b.chat("안녕", "ESTOP", 2)
    assert r["intent"] == "chat" and "비상정지" in r["say"]


def _msgs(role_texts):
    return [{"type": "message", "role": r, "text": t, "ts": 0} for r, t in role_texts]


def _sent(b):
    return b.chain.members[0].provider.messages


def test_chat_memory_order_roles_and_current_last(cfg):
    b = make(cfg, '{"intent": "chat", "say": "민수님!", "n": null}')
    hist = _msgs([("user", "내 이름은 민수야"), ("robot", "반가워요 민수님"), ("system", "알림")])
    b.chat("내 이름이 뭐라고 했지?", "IDLE", 0, history=hist)
    m = _sent(b)
    assert [x["role"] for x in m] == ["system", "user", "assistant", "user"]
    assert "보리" in m[0]["content"] and "'오란다'" in m[0]["content"]
    assert "{robot_name}" not in m[0]["content"] and "{target}" not in m[0]["content"]
    assert m[1]["content"] == "내 이름은 민수야" and m[2]["content"] == "반가워요 민수님"
    assert json.loads(m[3]["content"])["text"] == "내 이름이 뭐라고 했지?"


def test_memory_respects_turns_and_drops_leading_assistant(cfg):
    cfg["brain"]["memory_turns"] = 3
    b = make(cfg, '{"skill": "oranda_pickup", "say": "네"}')
    hist = _msgs([("user", "u1"), ("robot", "r1"), ("user", "u2"), ("robot", "r2")])
    b.decide(2, 0, "WORKING", None, hist)
    m = _sent(b)
    # 마지막 3개 = r1,u2,r2 -> 맨 앞 assistant r1 제거 -> u2,r2, 현재 요청
    assert [(x["role"], x["content"]) for x in m[1:3]] == [("user", "u2"), ("assistant", "r2")]
    assert [x["role"] for x in m] == ["system", "user", "assistant", "user"]


def test_memory_merges_same_roles_and_ignores_blank(cfg):
    b = make(cfg, '{"intent": "chat", "say": "응", "n": null}')
    hist = _msgs([("user", "a"), ("user", "b"), ("robot", "  "), ("robot", "c")])
    b.chat("d", "IDLE", 0, history=hist)
    m = _sent(b)
    assert [(x["role"], x["content"]) for x in m[1:3]] == [("user", "a\nb"), ("assistant", "c")]
    assert [x["role"] for x in m] == ["system", "user", "assistant", "user"]


def test_memory_user_tail_merges_with_current_request(cfg):
    b = make(cfg, '{"intent": "chat", "say": "응", "n": null}')
    b.chat("d", "IDLE", 0, history=_msgs([("user", "앞말")]))
    m = _sent(b)
    assert [x["role"] for x in m] == ["system", "user"]
    assert m[1]["content"].startswith("앞말\n")


def test_no_history_unchanged_and_default_persona(cfg):
    cfg["target"].pop("robot_name", None)
    b = make(cfg, '{"intent": "chat", "say": "응", "n": null}')
    b.chat("d", "IDLE", 0)
    m = _sent(b)
    assert [x["role"] for x in m] == ["system", "user"] and "보리" in m[0]["content"]


def test_keyword_dori_only_when_allowed():
    idle = allowed_intents("IDLE")
    for text in ("도리도리 해 봐", "고개 저어 봐", "고개를 저어 줘"):
        assert keyword_intent(text, idle) == "dori_dori"
    assert keyword_intent("도리도리 해 봐", allowed_intents("WORKING")) == "chat"
    assert keyword_intent("도리도리 해 봐", allowed_intents("DONE")) == "chat"


def test_chat_rules_dori_in_idle_only_and_testing_line(cfg):
    b = make(cfg)
    assert b.chat("도리도리 해 봐", "IDLE", 0) == {"intent": "dori_dori", "say": "도리도리~ 이렇게요?",
                                                "n": None, "source": "rules"}
    assert b.chat("도리도리 해 봐", "WORKING", 1)["intent"] == "chat"
    r = b.chat("옮겨줘", "TESTING", 0)
    assert r["intent"] == "chat" and r["say"] == "지금 테스트 중이에요. 끝나면 시켜 주세요!"


def test_chat_llm_dori_tool_only_in_idle(cfg):
    r = make(cfg, '{"intent": "dori_dori", "say": "싫어요~", "n": null}').chat("너 싫지?", "IDLE", 0)
    assert r == {"intent": "dori_dori", "say": "싫어요~", "n": None, "source": "fake"}


@pytest.mark.parametrize("state", ["DONE", "WORKING", "REFUSING", "TESTING", "ESTOP"])
def test_chat_llm_dori_ignored_outside_idle(cfg, state):
    assert "dori_dori" not in allowed_intents(state)
    r = make(cfg, '{"intent": "dori_dori", "say": "싫어요~", "n": null}').chat("너 싫지?", state, 2)
    assert r["intent"] == "chat" and r["say"] == "싫어요~"


def test_keyword_start_beats_dori():
    idle = allowed_intents("IDLE")
    assert keyword_intent("도리도리 하지 말고 옮겨줘", idle) == "start_task"
    assert keyword_intent("도리도리 그만하고 시작해", idle) == "start_task"


def test_chat_prompt_describes_dori_tool(cfg):
    fake = Scripted('{"intent": "chat", "say": "네", "n": null}')
    Brain(cfg, chain=Chain([Member("f", fake)]), rng=FirstRng()).chat("안녕", "IDLE", 0)
    system = fake.messages[0]["content"]
    assert "- dori_dori: 고개를 좌우로 젓는 동작 한 번 (도리도리를 해 보라고 하거나 고개를 저어 보라고 할 때만)" in system
    assert json.loads(fake.messages[-1]["content"])["allowed"] == ["start_task", "chat", "dori_dori"]


H = {"refuse": "half", "safe_max": 3, "force_refuse": 6, "max_retry": 2}


def test_refuse_at_values():
    from snackbot.brain import refuse_at
    assert [refuse_at(n) for n in (1, 2, 3, 4, 5, 6, 7)] == [None, None, 2, 2, 3, 3, 4]


def test_half_guard_table():
    assert allowed_skills(0, 3, H, total=6) == ["done"]
    assert allowed_skills(6, 0, H, total=6) == ["oranda_pickup"]
    assert allowed_skills(4, 2, H, total=6) == ["oranda_pickup"]
    assert allowed_skills(3, 3, H, total=6) == ["dori_dori"]
    assert allowed_skills(3, 3, H, total=6, refused=True) == ["oranda_pickup"]
    assert allowed_skills(1, 1, H, total=2) == ["oranda_pickup"]       # 2개 이하는 거부 없음
    assert allowed_skills(1, 2, H, total=3) == ["dori_dori"]
    assert allowed_skills(5, 0, H, total=3) == ["oranda_pickup"]       # 늘어난 경우 moved < 0 은 0
    assert allowed_skills(3, 3, {"safe_max": 3, "force_refuse": 6}, total=6) == ["oranda_pickup"]  # fixed 그대로


def test_half_tired_line_only_before_refusal(cfg):
    cfg["decision"]["refuse"] = "half"
    b = make(cfg)
    tired = ("으… 팔이 조금 뻐근한데요.", "이거 몇 개 남았어요?")
    assert b.decide(6, 0, "WORKING", total=6)["say"] not in tired
    assert b.decide(4, 2, "WORKING", total=6)["say"] in tired          # moved 2 == refuse_at 3 - 1
    assert b.decide(4, 2, "WORKING", total=6, refused=True)["say"] not in tired
    assert b.decide(3, 3, "WORKING", total=6)["skill"] == "dori_dori"
    assert b.decide(3, 3, "WORKING", total=2)["say"] not in tired
