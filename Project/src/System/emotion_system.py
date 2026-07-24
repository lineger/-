from typing import Dict, List

from System.action_request import ActionRequest

class EmotionSystem:
    """
    多維情感系統（向量）。
    - 直接 API：add/get/decay/attitudes/attitude_primary
    - 數值：整數，範圍 [-999, 999]；採「稀疏存放」
    - 魅力 (CHA)：僅對「正向情感」的正增量提供加成
    - Hub verbs：emotion_add / emotion_get / emotion_decay / emotion_attitudes / emotion_attitude
    """

    EMOTIONS: tuple[str, ...] = (
        "joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation"
    )

    # 多情感組合 → 多標籤態度（可同時命中多個）
    MULTI_LABEL_RULES = [
        ("hostile",     lambda e: e["anger"] + e["disgust"] >= 20 and e["trust"] <= 5),
        ("intimidated", lambda e: e["fear"] >= 15 and e["trust"] <= 5),
        ("wary",        lambda e: (e["fear"] >= 10 or e["disgust"] >= 10) and e["trust"] <= 10),
        ("friendly",    lambda e: e["trust"] + e["joy"] >= 25 and e["anger"] + e["disgust"] <= 8),
        ("warm",        lambda e: e["joy"] + e["anticipation"] >= 18 and e["trust"] >= 8 and e["fear"] < 10),
        ("admiring",    lambda e: e["trust"] >= 15 and e["joy"] >= 6),
        ("dependent",   lambda e: e["sadness"] >= 10 and e["trust"] >= 10),
        ("conflicted",  lambda e: e["anger"] >= 10 and e["trust"] >= 10),
        ("disgusted",   lambda e: e["disgust"] >= 12),
        ("fearful",     lambda e: e["fear"] >= 12),
        ("annoyed",     lambda e: e["anger"] >= 8),
        ("happy",       lambda e: e["joy"] >= 12),
        ("neutral",     lambda e: sum(abs(v) for v in e.values()) <= 8),
    ]

    verbs = ("emotion_add", "emotion_get", "emotion_decay",
             "emotion_attitudes", "emotion_attitude")
    priority = 75

    # ---------------- lifecycle ----------------
    def attach(self, *, say=print, world=None, hub=None):
        self.say   = say or (lambda *_: None)
        self.world = world or {}
        self.hub   = hub

    # ---------------- helpers ----------------
    def _emap(self, state, who: str) -> Dict[str, int]:
        # 新資料型態：存到 state.emotion.emotions
        return state.emotion.emotions.setdefault(who, {})

    def _pack(self, state, who: str) -> Dict[str, int]:
        raw = state.emotion.emotions.get(who, {})
        return {emo: int(raw.get(emo, 0)) for emo in self.EMOTIONS}

    def _name(self, who: str) -> str:
        npcs = (self.world.get("npcs") or {})
        return (npcs.get(who, {}) or {}).get("name", who)

    # ---------------- API ----------------
    def add(self, state, who: str, emotion: str, delta: int, *, silent: bool = False) -> int:
        """
        對某對象的某情感 += delta；回傳新值。
        joy/trust/anticipation 的正增量會吃 CHA 加成。
        """
        if emotion not in self.EMOTIONS:
            return 0
        emap = self._emap(state, who)
        cur  = int(emap.get(emotion, 0))
        real = int(delta)

        if emotion in ("joy", "trust", "anticipation") and real > 0:
            # 新結構：CHA 來自 state.attr.CHA
            cha = int(getattr(getattr(state, "attr", None), "CHA", 0))
            real += (real * cha // 10)

        newv = max(-999, min(999, cur + real))
        if newv == 0:
            emap.pop(emotion, None)
            if not emap:
                state.emotion.emotions.pop(who, None)
        else:
            emap[emotion] = newv

        if not silent:
            sign = "+" if real >= 0 else ""
            self.say(f"（{self._name(who)} 的 {emotion} {sign}{real} → {newv}）")
        return newv

    def get(self, state, who: str, emotion: str) -> int:
        if emotion not in self.EMOTIONS:
            return 0
        return int(state.emotion.emotions.get(who, {}).get(emotion, 0))

    def decay(self, state, *, rate: int = 1, baseline: int = 0) -> None:
        """全局衰減：讓所有情感逐步靠近 baseline（預設 0）。"""
        for who, emap in list(state.emotion.emotions.items()):
            for emo, val in list(emap.items()):
                v = int(val)
                if v > baseline:
                    v = max(baseline, v - rate)
                elif v < baseline:
                    v = min(baseline, v + rate)
                if v == 0:
                    emap.pop(emo, None)
                else:
                    emap[emo] = v
            if not emap:
                state.emotion.emotions.pop(who, None)

    def attitudes(self, state, who: str, *, max_labels: int = 3) -> List[str]:
        """回傳可能的多個態度標籤。"""
        e = self._pack(state, who)
        labels: List[str] = []
        for name, pred in self.MULTI_LABEL_RULES:
            try:
                if pred(e):
                    labels.append(name)
                    if len(labels) >= max_labels:
                        break
            except Exception:
                continue
        if not labels:
            labels = ["reserved"]
        return labels

    def attitude_primary(self, state, who: str) -> str:
        """取一個主要態度（多個標籤時挑第一個命中的）。"""
        return self.attitudes(state, who, max_labels=1)[0]

    # ---------------- Hub 介面 ----------------
    def can_fire(self, request: ActionRequest, state) -> bool:
        verb = request.verb
        if verb not in self.verbs:
            return False

        who = request.target_id
        if verb in ("emotion_get", "emotion_attitudes", "emotion_attitude"):
            return who is not None
        if verb == "emotion_add":
            return (
                who is not None
                and request.emotion in self.EMOTIONS
                and type(request.delta) is int
            )
        if verb == "emotion_decay":
            return True
        return False

    def fire(self, request: ActionRequest, state):
        verb = request.verb
        who = request.target_id

        if verb == "emotion_add":
            return self.add(
                state,
                who,
                request.emotion,
                request.delta or 0,
                silent=bool(request.silent),
            )
        if verb == "emotion_get":
            return self.get(state, who, request.emotion)
        if verb == "emotion_decay":
            self.decay(state, rate=request.rate if request.rate is not None else 1)
            return True
        if verb == "emotion_attitudes":
            limit = request.max_labels if request.max_labels is not None else 3
            return self.attitudes(state, who, max_labels=limit)
        if verb == "emotion_attitude":
            return self.attitude_primary(state, who)
        return False
