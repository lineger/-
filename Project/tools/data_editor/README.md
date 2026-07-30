# 遊戲 JSON 資料編輯器

從 `Project` 目錄執行：

```bash
python tools/data_editor/main.py
```

也可以指定其他資料集：

```bash
python tools/data_editor/main.py path/to/data
```

目前支援：

- 戰鬥 Tags
- 社交 Roles
- 物品種類 Kinds
- 裝備欄位 Slots
- 種族 Species（與材質／元素 Tags 分離）
- 狀態效果、Skills、Monsters
- Items
- Rooms（含結構化遭遇池）
- NPC 基本資料、種族、技能挑選、數值屬性、對話 JSON、送禮規則建構器
- Quests、前置任務與 `deliver_item` 目標建構器

儲存前會做跨檔引用驗證。舊檔備份在資料目錄下的 `.editor_backups/`，正式檔採臨時檔驗證後原子替換。

「格式化全部」會依每種資料的語意順序排列欄位、依 ID 排列集合，並保留任務目標、對話選項等具有順序意義的陣列。

## Kind 與裝備欄索引

Item 的 `kind` 與 `slot` 不再需要手動輸入任意字串，會分別引用：

```text
item_kinds.json
equipment_slots.json
```

可以從左側分類完整維護，也可以在 Item 表單旁按「＋新增」。快速新增完成後，新 ID 會立刻加入目前下拉選單並自動套用，不必重新啟動編輯器。

刪除仍被 Item 引用的 Kind 或 Slot 時，跨檔驗證會阻止寫入。

## 可搜尋屬性編輯器

以下欄位使用可搜尋的屬性目錄：

- Item：`bonuses`、`simple_use`
- NPC：`attr`、`stats`、`combat`

可以搜尋欄位 ID、中文名稱或說明，例如：

```text
hp_delta
HP
魅力
物理攻擊
```

選擇屬性後輸入值即可加入或更新。整數、布林值等會依欄位契約解析；未列在目錄中的自訂 key 仍可手動輸入並保留。

## 搜尋與篩選

- 項目清單上方的「搜尋」會比對 ID、名稱與目前資料內容。
- 「篩選」可依分類選擇 Tag、Role、Kind、Slot、房間、任務類型、收件條件等欄位。
- NPC、Monster、Item、Room、Quest 表單中的多選清單各自有搜尋框；切換搜尋文字時，已選取但暫時隱藏的項目仍會保留。
- 屬性編輯器也有獨立搜尋欄，不必在大型 JSON object 中逐行尋找欄位。

## 驗證範圍

驗證器主要檢查 JSON 型別、ID 格式、跨檔引用與已明確定義的資料契約，例如：

- 不存在的 Room、Item、NPC、Monster、Skill、Status、Species、Tag、Role、Kind、Slot、Quest
- `bonuses` 的值是否為數字
- `hp_delta`、`mp_delta`、`gold_delta` 是否為整數
- `consume` 是否為布林值
- 交付目標的 NPC／Role 衝突
- `rooms.encounters.pool` 的怪物 ID 與權重
- `npcs.skills`、`monsters.skills` 的技能 ID
- `topics.*.effects[].quest_id` 與 `tags.on_hit_proc.status`
- Quest 前置任務不存在、自我引用或形成循環

它目前不推論完整世界邏輯，例如同一名 NPC 同時列在多個 Room、出口是否必然成對、任務是否實際可完成。這類規則在日夜與 Schedule 的位置權威來源確定後，再加入才不會把暫時允許的設計誤判為錯誤。

## Kind 行為契約

`item_kinds.json` 現在不只保存顯示名稱，也能描述 Item 編輯契約：

```json
{
  "weapon": {
    "name": "武器",
    "allowed_actions": ["equip", "gift", "deliver", "trade"],
    "required_fields": ["slot"],
    "allowed_slots": ["weapon", "offhand"]
  },
  "consumable": {
    "name": "消耗品",
    "allowed_actions": ["use", "gift", "deliver", "trade"],
    "required_fields": ["simple_use"],
    "stackable": true,
    "default_max_stack": 20
  }
}
```

Item 表單會依 Kind 動態顯示：

- `equip`：裝備欄與 `bonuses`
- `use`：可搜尋的 `simple_use`
- `target_use`：`uses`
- `stackable`：Item 層級的 `max_stack` 覆寫欄位

若 Item 已有與新 Kind 不相容的舊欄位，編輯器不會自動刪除，而會保留該欄並在 Kind 摘要中標示衝突，讓使用者自行確認後移除。

Kind 可定義 `allowed_slots`，Item 的裝備欄下拉選單會只列出允許欄位。從 Item 表單快速新增 Slot 時，若目前 Kind 使用限制清單，新 Slot 會同步加入該 Kind 並立即刷新表單。

目前 `gift`、`deliver`、`trade` 是 Kind 的語意與未來系統契約；實際 NPC 是否收禮、任務是否接受交付，仍分別由 NPC gifts 與 QuestSystem 判斷。`default_max_stack` 目前也先作為資料契約，背包尚未強制限制堆疊數量。

## 種族與戰鬥 Tags

`species.json` 保存互斥的單一種族，例如 `human`、`ghost`、`construct`、`beast`。NPC 與 Monster 使用 `species` 單選欄位；材質、元素、武器特徵與技能分類仍放在 `tags.json` 的多選集合。

戰鬥結算會把角色的 `species` ID 併入防禦標籤，因此 `tags.json` 的倍率規則仍可直接指定種族，例如讓 `holy.multipliers.ghost = 2.0`，不必複製一套傷害公式。

## 任務鏈

Quest 可使用：

```json
"requires": ["Q_PREVIOUS"]
```

只有當所有前置任務都在 `state.quest.completed` 中，`QuestSystem` 才允許接受。編輯器會排除目前任務本身，並阻止不存在的 ID 與循環依賴。
