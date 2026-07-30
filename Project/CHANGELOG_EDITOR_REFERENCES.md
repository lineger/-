# 編輯器與資料引用更新

日期：2026-07-29

## 已完成

- 新增 `Monsters`、`Skills`、`狀態效果`、`Species` 編輯分類。
- `rooms.encounters.pool` 改為怪物挑選器與權重表格，不再手寫 Monster ID。
- `npcs.skills` 與 `monsters.skills` 改為可搜尋多選清單。
- `tags.on_hit_proc.status` 改為狀態效果下拉選單，機率改為獨立整數欄位。
- NPC Topic 新增 `quest_accept` 結構化加入按鈕；Quest ID 從既有任務挑選。
- Quest 新增 `requires` 前置任務多選欄位；引擎只允許完成全部前置任務後接受。
- 驗證器新增 Monster、Skill、Status、Species、遭遇池、Topic Quest 與任務循環檢查。
- 遊戲載入器同步加入相同的高風險跨檔引用驗證，手動改 JSON 也會被攔截。
- 新增 `species.json`，NPC／Monster 使用單一 `species`；種族 ID 在戰鬥時計入防禦標籤，仍可沿用 Tag 倍率表。
- 將 `human`、`ghost` 從 `tags.json` 遷移至 `species.json`；補齊現有 NPC 與 Monster 的 species。
- 補上既有 NPC 已引用但缺失的 `weaken` 技能，並補齊現有技能使用的 Tag 定義。

## 未動項目

- 未替現有事件系統製作編輯器。
- 未實作交易系統；避免與預定重寫的事件觸發流程耦合。
- 未替現有任務任意指定前置鏈，只提供資料欄位、驗證與引擎支援。

## 驗證結果

- 全資料跨檔驗證：0 errors、0 warnings。
- 編輯器所有 12 個分類均完成表單建立與資料收集煙霧測試。
- 已測試並成功攔截：錯誤 Monster ID、Skill ID、Quest ID、Status ID、Quest 循環依賴。
- `load_world`、Engine import、Quest 前置條件與 Species 倍率共用途徑皆通過測試。
