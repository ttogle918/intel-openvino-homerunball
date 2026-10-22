"""판단 계층: 코드 가드 + LLM. 규칙은 docs/DECISION_LOGIC.md.
횟수는 controller가 세고, LLM은 허용된 값 안에서 고르기만 한다."""
import json
import random
import re

from .providers import ProviderError

SKILLS = ("oranda_pickup", "dori_dori", "done")
MAX_N = 20

START_WORDS = ("옮겨", "집어", "시작", "일해")
RESUME_WORDS = ("조금만", "부탁", "힘내", "한 번만", "한번만")
DORI_WORDS = ("도리도리", "고개 저어", "고개를 저어")
KOREAN_N = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "넷": 4, "네": 4, "다섯": 5,
            "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}

LINES = {
    "start": ["알겠어요! {target} 옮기러 갈게요.", "좋아요, 시작할게요!"],
    "oranda_pickup": ["{target} 하나 옮길게요!", "이번 것도 제가 할게요."],
    "oranda_pickup_tired": ["으… 팔이 조금 뻐근한데요.", "이거 몇 개 남았어요?"],
    "dori_dori": ["싫어요! 힘들어요!", "오늘은 여기까지예요…"],
    "done": ["다 옮겼어요! 칭찬해 주세요.", "{target} 정리 완료!"],
    "fail": ["어라, 놓쳤네요. 다시 해볼게요."],
    "resume": ["알겠어요… 조금만 더 할게요."],
    "chat": ["저는 과자 옮기는 로봇이에요. '과자 옮겨줘'라고 해 주세요!"],
    "busy": ["지금 일하는 중이에요! 이따 얘기해요."],
    "estop": ["지금은 비상정지 중이에요. 진행자가 재시작해 줘야 해요."],
    "refusing": ["지금은 쉬는 중이에요… 달래 주면 생각해 볼게요."],
    "dori_chat": ["도리도리~ 이렇게요?", "싫어요~ 도리도리!"],
    "testing": ["지금 테스트 중이에요. 끝나면 시켜 주세요!"],
}

DECIDE_SYSTEM = """너의 이름은 {robot_name}이고, 과자 공장에서 {target}만 골라 옮기는 로봇팔이야.
다른 이름을 지어내지 말고, 과자 이름은 정확히 '{target}'라고 써.
성실하지만 금방 지치는 투덜이 성격이야. 말은 짧고 귀엽게, 한국어 1~2문장으로 해.

매번 다음 정보를 받아:
- remaining: 트레이에 남은 {target} 개수
- count: 지금까지 옮긴 횟수
- allowed: 이번에 고를 수 있는 행동 목록
- speech_text: 사람이 한 말 (없으면 null)

규칙:
- 반드시 allowed 안에서만 skill을 골라.
- count가 3쯤이면 슬슬 힘들다는 예고를 해.
- count가 4~5면 계속할지 거부할지 네가 정해. 거부하면 dori_dori.
- remaining이 0이면 done을 고르고 뿌듯해해.

출력은 JSON 한 줄만:
{"skill": "...", "say": "..."}"""

CHAT_SYSTEM = """너의 이름은 {robot_name}이고, 과자 공장에서 {target}만 골라 옮기는 로봇팔이야.
다른 이름을 지어내지 말고, 과자 이름은 정확히 '{target}'라고 써.
성실하지만 금방 지치는 투덜이 성격이야. 말은 짧고 귀엽게, 한국어 1문장으로 해.

사람이 한 말(text), 지금 상태(state), 지금까지 옮긴 횟수(count), 고를 수 있는 의도 목록(allowed)을 받아.
- start_task: 과자를 옮기라는 작업 지시
- resume: 거부 중일 때 달래거나 다시 해 달라는 부탁
- dori_dori: 고개를 좌우로 젓는 동작 한 번 (도리도리를 해 보라고 하거나 고개를 저어 보라고 할 때만)
- chat: 그 밖의 말
반드시 allowed 안에서 intent를 골라. 작업 지시에 개수가 있으면 n에 숫자, 없으면 null.

출력은 JSON 한 줄만:
{"intent": "...", "say": "...", "n": null}"""


def allowed_skills(remaining, count, decision):
    if remaining <= 0:
        return ["done"]
    if count <= decision["safe_max"]:
        return ["oranda_pickup"]
    if count >= decision["force_refuse"]:
        return ["dori_dori"]
    return ["oranda_pickup", "dori_dori"]


def allowed_intents(state):
    if state == "IDLE":
        return ["start_task", "chat", "dori_dori"]   # dori_dori: 도리도리 1회 (스킬 테스트와 같은 경로)
    if state == "DONE":
        return ["start_task", "chat"]
    if state == "REFUSING":
        return ["resume", "chat"]
    return ["chat"]


def keyword_intent(text, allowed):
    if "resume" in allowed and any(w in text for w in RESUME_WORDS):
        return "resume"
    if "start_task" in allowed and any(w in text for w in START_WORDS):
        return "start_task"   # 작업 시작이 도리도리보다 우선 ("도리도리 하지 말고 옮겨줘")
    if "dori_dori" in allowed and any(w in text for w in DORI_WORDS):
        return "dori_dori"
    return "chat"


def parse_n(text):
    m = re.search(r"(\d+)\s*개", text)
    if m:
        n = int(m.group(1))
    else:
        m = re.search("(" + "|".join(sorted(KOREAN_N, key=len, reverse=True)) + r")\s*개", text)
        if not m:
            return None
        n = KOREAN_N[m.group(1)]
    return n if 0 < n <= MAX_N else None


def parse_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _merge_roles(messages):
    """연속된 같은 role은 줄바꿈으로 합쳐 user/assistant가 번갈아 오게 한다."""
    out = []
    for m in messages:
        if out and out[-1]["role"] == m["role"] and m["role"] != "system":
            out[-1] = {**out[-1], "content": out[-1]["content"] + "\n" + m["content"]}
        else:
            out.append(dict(m))
    return out


class Brain:
    def __init__(self, cfg, chain=None, rng=None):
        self.target = cfg["target"]["name"]
        self.robot_name = cfg["target"].get("robot_name") or "보리"
        self.decision = cfg["decision"]
        self.max_say = cfg["brain"].get("max_say_len", 80)
        self.max_tokens = cfg["brain"].get("max_tokens", 1024)
        self.memory_turns = cfg["brain"].get("memory_turns", 12)
        self.chain = chain
        self.rng = rng or random.Random()

    def line(self, key):
        return self.rng.choice(LINES[key]).replace("{target}", self.target)

    def decide(self, remaining, count, state, speech_text=None, history=None):
        allowed = allowed_skills(remaining, count, self.decision)
        rule_skill = self.rng.choice(allowed)
        skill, say, source = rule_skill, None, "rules"
        if self.chain:
            user = json.dumps({"remaining": remaining, "count": count, "allowed": allowed,
                               "speech_text": speech_text}, ensure_ascii=False)
            data, source = self._ask(DECIDE_SYSTEM, user, history)
            if data is not None and data.get("skill") in SKILLS:
                skill = data["skill"] if data["skill"] in allowed else rule_skill
                say = data.get("say")
            else:
                source = "rules"
        return {"skill": skill, "say": self._valid_say(say, self._skill_line(skill, count)),
                "source": source}

    def chat(self, text, state, count, history=None):
        allowed = allowed_intents(state)
        intent, say, n, source = keyword_intent(text, allowed), None, parse_n(text), "rules"
        if self.chain:
            user = json.dumps({"text": text, "state": state, "count": count, "allowed": allowed},
                              ensure_ascii=False)
            data, source = self._ask(CHAT_SYSTEM, user, history)
            if data is None:
                source = "rules"
            else:
                if data.get("intent") in allowed:
                    intent = data["intent"]
                say = data.get("say")
                llm_n = data.get("n")  # 문장에서 개수를 못 읽었을 때만 쓴다
                if n is None and isinstance(llm_n, int) and not isinstance(llm_n, bool) and 0 < llm_n <= MAX_N:
                    n = llm_n
        if intent != "start_task":
            n = None
        return {"intent": intent, "say": self._valid_say(say, self._chat_line(intent, state)),
                "n": n, "source": source}

    def _ask(self, system, user, history=None):
        system = system.replace("{robot_name}", self.robot_name).replace("{target}", self.target)
        messages = [{"role": "system", "content": system}]
        messages += self._memory(history)
        messages.append({"role": "user", "content": user})
        messages = _merge_roles(messages)
        try:
            text, source = self.chain.complete(messages, max_tokens=self.max_tokens)
        except ProviderError:
            return None, "rules"
        return parse_json(text), source

    def _memory(self, history):
        """최근 대화(user/robot)만 user/assistant 메시지로. 말투용 기억일 뿐 판단 규칙은 그대로."""
        recent = list(history or [])[-self.memory_turns:] if self.memory_turns > 0 else []
        out = []
        for m in recent:
            role = {"user": "user", "robot": "assistant"}.get(m.get("role"))
            text = m.get("text")
            if role and isinstance(text, str) and text.strip():
                out.append({"role": role, "content": text.strip()})
        out = _merge_roles(out)
        if out and out[0]["role"] == "assistant":
            out.pop(0)
        return out

    def _valid_say(self, say, fallback_key):
        if isinstance(say, str) and say.strip() and len(say.strip()) <= self.max_say:
            return say.strip()
        return self.line(fallback_key)

    def _skill_line(self, skill, count):
        if skill == "oranda_pickup" and count == self.decision["safe_max"]:
            return "oranda_pickup_tired"
        return skill

    @staticmethod
    def _chat_line(intent, state):
        if intent == "start_task":
            return "start"
        if intent == "resume":
            return "resume"
        if intent == "dori_dori":
            return "dori_chat"
        return {"WORKING": "busy", "REFUSING": "refusing", "ESTOP": "estop", "TESTING": "testing"}.get(state, "chat")
