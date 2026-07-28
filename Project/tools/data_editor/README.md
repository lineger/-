# 遊戲 JSON 資料編輯器

從 `Project` 目錄執行：

```bash
python tools/data_editor/main.py
```

也可以指定其他資料集：

```bash
python tools/data_editor/main.py path/to/data
```

第一版支援：

- 戰鬥 Tags
- 社交 Roles
- Items
- Rooms
- NPC 基本資料、對話 JSON、送禮規則建構器
- Quests 與 `deliver_item` 目標建構器

儲存前會做跨檔引用驗證。舊檔備份在資料目錄下的 `.editor_backups/`，正式檔採臨時檔驗證後原子替換。

「格式化全部」會依每種資料的語意順序排列欄位、依 ID 排列集合，並保留任務目標、對話選項等具有順序意義的陣列。

## 搜尋與篩選

- 項目清單上方的「搜尋」會比對 ID、名稱與目前資料內容。
- 「篩選」可依分類選擇 Tag、Role、房間、任務類型、收件條件等欄位。
- NPC、Item、Room 表單中的多選清單各自有搜尋框；切換搜尋文字時，已選取但暫時隱藏的項目仍會保留。

## 驗證範圍

驗證器主要檢查 JSON 型別、ID 格式、跨檔引用與已明確定義的資料契約，例如不存在的 Room、Item、NPC、Tag、Role，以及交付目標的衝突條件。

它目前不推論完整世界邏輯，例如同一名 NPC 同時列在多個 Room、出口是否必然成對、任務是否實際可完成。這類規則在日夜與 Schedule 的位置權威來源確定後，再加入才不會把暫時允許的設計誤判為錯誤。

