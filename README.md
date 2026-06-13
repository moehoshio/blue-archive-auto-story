# Blue Archive 自動劇情工具

在宿主機執行, 透過 ADB 控制遊戲, 用 OpenCV 多尺度模板匹配辨識畫面狀態,
自動完成主線 / 活動劇情 (自動跳過劇情、進入並設定戰鬥、翻頁), 直到本章完成。

## 前置設定 (重要)
在遊戲內請先開啟:
- **自動下一章**
- **自動連續播放**
- 語言切換為 **English** (`assets/` 為英文截圖)

並確保裝置已連上 ADB:
```
adb devices
```

## 安裝
```
pip install -r requirements.txt
```

## 使用
```
python main.py                 # 啟動自動劇情 (主線/活動)
python main.py --momotalk      # 啟動好感劇情 (MomoTalk) 自動化
python main.py --probe         # 只截一次圖, 列出偵測到的元素 (不點擊), 用來調門檻/尺度
python main.py --probe --save probe.png
```
`config.yaml` 可調整 adb 路徑/序號、匹配門檻與尺度範圍、循環間隔、目標倍速、重連上限等。

## 運作流程
反應式狀態機, 每個 tick 截一次圖, 依優先序處理 (第一個命中即動作):
1. 斷線 → `notice_reconnect` 重試 (超過上限停止)
2. 戰鬥暫停彈窗 → `common_button_continue` 恢復
3. 戰鬥結算 → `combat_completed_confirm` 確認
4. 待出擊 → `combat_mobilize` 進入戰鬥
5. 戰鬥內 → 開啟 `AUTO`、把倍速調到目標值
6. 劇情 → 展開 `menu` → `story_skip` → `story_skip_confirm`
7. 列表頁 → `story_enter_episode` / `next_page` / `story_enter`

連續多個 tick 無任何可操作元素時:
- 若期間看過 `story_cleared` → 視為本章完成, 正常結束
- 否則視為卡住, 要求人工介入

## 好感劇情 (MomoTalk, `--momotalk`)
獨立任務, 把每個未讀對話跑完。每 tick 截圖, 依優先序處理:
1. 領獎頁 `momotalk_reward`（劇情跳過後的 TOUCH TO CONTINUE）→ 點擊繼續
2. 一般劇情畫面（好感劇情本體, Auto/Menu）→ 沿用主線跳過流程（開選單→Skip→確認）
3. 好感劇情入口 `momotalk_story_begin` / `momotalk_story_enter` → 進入劇情
4. 對話中有回覆選項 `momotalk_reply`（| Reply 標籤）→ 點其下方第一個選項（好感任意選）
5. 無可操作元素且對話面板靜止（非「對方輸入中」）達數 tick → 切換下一個未讀對話
6. 連續切換多次仍無進展 → 關閉並重開 MomoTalk 刷新列表
7. 重開後主畫面入口已無紅點（無未讀）→ 任務結束

辨識以模板為主；劇情列表的頭像/分頁/紅點無法穩定模板化, 那些純位置點擊改用
『參考解析度 1920x1080 座標 × 實際縮放』(見 `config.yaml` 的 `momotalk` 與
`src/config.py` 的 `MomoTalkConfig`)。回覆選項文字每次不同, 故以固定的「| Reply」標籤
為錨點, 點其右下固定位移處的選項；「對方輸入中/新訊息」以對話面板兩 tick 的畫面差判定。

## 專案結構
```
main.py              進入點 / probe 偵錯指令
config.yaml          設定
assets/              元素模板截圖
src/
  config.py          設定載入 (dataclass)
  adb.py             ADB 截圖 + 點擊
  vision.py          多尺度模板匹配 (含尺度快取)
  assets.py          邏輯狀態名 → 模板檔案註冊表
  automator.py       反應式狀態機主循環 (主線劇情)
  momotalk.py        好感劇情 (MomoTalk) 自動化
  logging_setup.py   日誌
```
