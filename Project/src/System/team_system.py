from typing import Dict, Any, Optional, List
from Data.state import NPCProfile

class TeamSystem:
    """
    隊伍系統（鴨子型別）：
      verbs: recruit / dismiss / party
      - 所有 NPC 可招募；上限 3；無替補
      - 招募：NPC 必須在玩家當前房間；記錄 home = 當前房；從房間移除
      - 踢人：從隊伍移除並送回 home（若遺失則送回玩家當前房），加回房間 npcs
      - party：列出成員
    狀態儲存於 state.facts：
      _party_members: List[str]
      _party_home:    Dict[str, str]  # npc_id -> room_id
    """
    verbs    = ("recruit", "dismiss", "party")
    priority = 40

    def attach(self, *, say=print, world=None, hub=None):
        self.say   = say or (lambda *_: None)
        self.world = world or {}
        self.hub   = hub

    # ---------- internal: state access ----------
    @staticmethod
    def _members(state) -> List[str]:
        return state.facts.setdefault("_party_members", [])

    @staticmethod
    def _homes(state) -> Dict[str, str]:
        return state.facts.setdefault("_party_home", {})

    # ---------- internal: world helpers ----------
    def _npc_exists(self, npc_id: str) -> bool:
        return npc_id in (self.world.get("npcs") or {})

    def _room_has_npc(self, room_id: str, npc_id: str) -> bool:
        room = (self.world.get("rooms") or {}).get(room_id, {})
        return npc_id in (room.get("npcs") or [])

    def _remove_npc_from_room(self, room_id: str, npc_id: str) -> None:
        room = (self.world.get("rooms") or {}).get(room_id, {})
        npcs = room.setdefault("npcs", [])
        try:
            npcs.remove(npc_id)
        except ValueError:
            pass

    def _add_npc_to_room(self, room_id: str, npc_id: str) -> None:
        rooms = self.world.get("rooms") or {}
        room  = rooms.get(room_id)
        if not room:
            # 找不到房間就丟回玩家目前房
            room_id = list(rooms.keys())[0] if rooms else None
            room    = rooms.get(room_id, {})
        npcs = room.setdefault("npcs", [])
        if npc_id not in npcs:
            npcs.append(npc_id)

    def _npc_name(self, npc_id: str) -> str:
        return (self.world.get("npcs", {}).get(npc_id, {}) or {}).get("name", npc_id)

    def _ensure_npc_profile(self, state, target_id: str):
        if target_id in state.npc_profiles:
            return
        world = self.world
        src = (world.get("npcs", {}) or {}).get(target_id, {})  # 初始資料來源
        c   = src.get("combat", {}) or {}

        prof = NPCProfile()
        prof.name   = src.get("name", target_id)
        prof.lvl    = int(src.get("lvl") or src.get("level") or 1)
        prof.exp    = int(src.get("exp", 0))

        # HP/MP：沒給就用 combat.hp 當 max
        base_hp = int(c.get("hp", src.get("hp", 10)))
        prof.max_hp = int(src.get("max_hp", base_hp))
        prof.hp     = int(src.get("hp", base_hp))
        prof.max_mp = int(src.get("max_mp", src.get("mp", 0)))
        prof.mp     = int(src.get("mp", 0))

        # 戰鬥參數
        prof.atk     = int(c.get("atk", src.get("atk", 5)))
        prof.defense = int(c.get("def", src.get("defense", 1)))
        prof.matk    = int(c.get("matk", src.get("matk", 0)))
        prof.mdef    = int(c.get("mdef", src.get("mdef", 0)))
        prof.speed   = int(c.get("speed", src.get("speed", 3)))
        prof.crit    = int(c.get("crit", src.get("crit", 0)))

        # 屬性六圍（若 world 有 attr 區段就吃）
        attr = src.get("attr", {}) or {}
        for k in ("STR","INT","CON","DEX","CHA","LCK"):
            setattr(prof, k, int(attr.get(k, getattr(prof, k))))

        # 裝備（以 world 初值為基礎）
        prof.equipment = dict(src.get("equipment") or {})

        # 技能：從 world.npcs[nid].skills 初始化一次
        init_sk = list(src.get("skills", []) or [])
        prof.skills = list(dict.fromkeys(init_sk))  # 去重

        state.npc_profiles[target_id] = prof

    # ---------- hub interface ----------
    def can_fire(self, verb, state, *, target_id: Optional[str] = None, **_):
        if verb == "party":
            return True

        if verb == "recruit":
            if not target_id or not self._npc_exists(target_id):
                return False
            mem = self._members(state)
            if target_id in mem or len(mem) >= 3:
                return False
            return self._room_has_npc(state.room_id, target_id)

        if verb == "dismiss":
            return bool(target_id and (target_id in self._members(state)))

        return False

    def fire(self, verb, state, *, target_id: Optional[str] = None, **_):
        if verb == "party":
            names = [self._npc_name(nid) for nid in self._members(state)]
            return {"ok": True, "text": "隊伍成員：" + ("、".join(names) if names else "（空）")}

        if verb == "recruit" and target_id:
            mem = self._members(state)
            if len(mem) >= 3:
                return {"ok": False, "text": "隊伍已滿（上限 3）。"}
            if target_id in mem:
                return {"ok": False, "text": "她已在你的隊伍中。"}
            if not self._room_has_npc(state.room_id, target_id):
                return {"ok": False, "text": "她不在這裡。"}

            # 記錄 home 並移出房間
            self._homes(state)[target_id] = state.room_id
            self._remove_npc_from_room(state.room_id, target_id)
            mem.append(target_id)
            self._ensure_npc_profile(state, target_id)

            return {"ok": True, "text": f"{self._npc_name(target_id)} 加入了隊伍。"}

        if verb == "dismiss" and target_id:
            mem  = self._members(state)
            home = self._homes(state).get(target_id) or state.room_id

            # 回家＋移除
            self._add_npc_to_room(home, target_id)
            try:
                mem.remove(target_id)
            except ValueError:
                pass
            self._homes(state).pop(target_id, None)

            room_name = (self.world.get("rooms", {}).get(home, {}) or {}).get("name", home)
            return {"ok": True, "text": f"你讓 {self._npc_name(target_id)} 回到「{room_name}」。"}

        return {"ok": False}
