from __future__ import annotations

from dataclasses import dataclass, fields
from typing import ClassVar, Mapping, FrozenSet


@dataclass(frozen=True, slots=True)
class ActionRule:
    """描述一個 verb 允許與必須提供的 ActionRequest 欄位。"""

    allowed: FrozenSet[str] = frozenset()
    required: FrozenSet[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """
    一次性的動作請求。

    所有跨越 Engine -> SystemsHub -> System 的動作參數都集中在這裡。
    frozen=True 防止傳遞途中被修改；slots=True 防止誤加拼錯的屬性。
    """

    verb: str

    # 通用目標
    item_id: str | None = None
    target_id: str | None = None

    # 專用語意欄位
    slot: str | None = None
    actor_id: str | None = None
    action: str | None = None
    topic_id: str | None = None
    quest_id: str | None = None

    # 情緒系統
    emotion: str | None = None
    delta: int | None = None
    silent: bool | None = None
    rate: int | None = None
    max_labels: int | None = None

    RULES: ClassVar[Mapping[str, ActionRule]] = {
        # Engine / event hooks
        "go": ActionRule(),
        "enter": ActionRule(),

        # SimpleSystem
        "talk": ActionRule(frozenset({"target_id"}), frozenset({"target_id"})),
        "give": ActionRule(
            frozenset({"item_id", "target_id"}),
            frozenset({"item_id", "target_id"}),
        ),
        "use": ActionRule(
            frozenset({"item_id", "target_id"}),
            frozenset({"item_id"}),
        ),

        # TalkSystem
        "talk_open": ActionRule(frozenset({"target_id"}), frozenset({"target_id"})),
        "talk_say": ActionRule(
            frozenset({"target_id", "topic_id"}),
            frozenset({"target_id", "topic_id"}),
        ),
        "talk_give": ActionRule(
            frozenset({"target_id", "item_id"}),
            frozenset({"target_id", "item_id"}),
        ),

        # EquipEngine
        "equip": ActionRule(frozenset({"item_id"}), frozenset({"item_id"})),
        "unequip": ActionRule(frozenset({"slot"}), frozenset({"slot"})),

        # TeamSystem
        "recruit": ActionRule(frozenset({"target_id"}), frozenset({"target_id"})),
        "dismiss": ActionRule(frozenset({"target_id"}), frozenset({"target_id"})),
        "party": ActionRule(),

        # CombatEngine
        "ambush": ActionRule(),
        "engage": ActionRule(frozenset({"target_id"}), frozenset({"target_id"})),
        "combat_act": ActionRule(
            frozenset({"actor_id", "action", "item_id", "target_id"}),
            frozenset({"actor_id", "action"}),
        ),

        # QuestSystem
        "quest_log": ActionRule(),
        "quest_accept": ActionRule(frozenset({"quest_id"}), frozenset({"quest_id"})),

        # EmotionSystem
        "emotion_add": ActionRule(
            frozenset({"target_id", "emotion", "delta", "silent"}),
            frozenset({"target_id", "emotion", "delta"}),
        ),
        "emotion_get": ActionRule(
            frozenset({"target_id", "emotion"}),
            frozenset({"target_id", "emotion"}),
        ),
        "emotion_decay": ActionRule(frozenset({"rate"})),
        "emotion_attitudes": ActionRule(
            frozenset({"target_id", "max_labels"}),
            frozenset({"target_id"}),
        ),
        "emotion_attitude": ActionRule(
            frozenset({"target_id"}),
            frozenset({"target_id"}),
        ),
    }

    _STRING_FIELDS: ClassVar[FrozenSet[str]] = frozenset({
        "item_id",
        "target_id",
        "slot",
        "actor_id",
        "action",
        "topic_id",
        "quest_id",
        "emotion",
    })
    _INT_FIELDS: ClassVar[FrozenSet[str]] = frozenset({"delta", "rate", "max_labels"})

    def __post_init__(self) -> None:
        if not isinstance(self.verb, str) or not self.verb.strip():
            raise TypeError("ActionRequest.verb 必須是非空字串")

        supplied = self.supplied_fields()
        rule = self.RULES.get(self.verb)
        if rule is None:
            raise ValueError(f"不支援的 verb：{self.verb!r}")

        unknown_for_verb = supplied - rule.allowed
        if unknown_for_verb:
            names = ", ".join(sorted(unknown_for_verb))
            raise TypeError(f"{self.verb!r} 不接受參數：{names}")

        missing = rule.required - supplied
        if missing:
            names = ", ".join(sorted(missing))
            raise TypeError(f"{self.verb!r} 缺少必要參數：{names}")

        for name in self._STRING_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"ActionRequest.{name} 必須是字串或 None")

        for name in self._INT_FIELDS:
            value = getattr(self, name)
            if value is not None and type(value) is not int:
                raise TypeError(f"ActionRequest.{name} 必須是 int 或 None")

        if self.silent is not None and type(self.silent) is not bool:
            raise TypeError("ActionRequest.silent 必須是 bool 或 None")

    @classmethod
    def build(cls, verb: str, **params) -> "ActionRequest":
        """建立並驗證請求；未知欄位會在入口立即報錯。"""

        valid = {field.name for field in fields(cls) if field.init and field.name != "verb"}
        unknown = set(params) - valid
        if unknown:
            names = ", ".join(sorted(unknown))
            raise TypeError(f"{verb!r} 收到未知參數：{names}")
        return cls(verb=verb, **params)

    def supplied_fields(self) -> FrozenSet[str]:
        return frozenset(
            field.name
            for field in fields(self)
            if field.name != "verb" and getattr(self, field.name) is not None
        )
