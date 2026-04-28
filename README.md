# blue-archive-auto-story

> **bass** – Blue Archive Auto Story

一個運行在宿主機上的工具，透過 **adb** 控制連線中的 Android 裝置（或模擬器），自動完成
*Blue Archive* 的劇情/活動故事，包含戰鬥關卡的自動進入與倍速＋AUTO 設定。

> ⚠️ 本工具僅供個人學習與輔助用途。它**只模擬玩家點擊**，不修改遊戲檔案、不進行封包破解。
> 使用者需自行承擔風險，遵守遊戲服務條款。

## 功能

1. 透過 adb 截取螢幕畫面，使用 OpenCV 模板匹配解析元素、位置、狀態。
2. 自動處理並完成劇情/活動章節（推進對話、選擇選項、收下獎勵）。
3. 戰鬥關卡自動進入，並啟用倍速 (x2) 與 AUTO 技能。

## 系統需求

- Python **3.10+**
- 已安裝 **adb**（[Android Platform Tools](https://developer.android.com/studio/releases/platform-tools)）並可被 `adb devices` 偵測到
- 一台已開啟 USB 偵錯的真機，或一個 Android 模擬器（MuMu / BlueStacks / 雷電…）

## 安裝

```bash
git clone https://github.com/moehoshio/blue-archive-auto-story.git
cd blue-archive-auto-story
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # 或：pip install -r requirements.txt
```

可選的 OCR 後端：

```bash
pip install -e ".[ocr]"            # 使用 pytesseract（需另裝 tesseract 二進位）
pip install -e ".[ocr-paddle]"     # 使用 paddleocr
```

## 快速開始

```bash
# 1) 確認 adb 看得到裝置
adb devices

# 2) 列出 bass 偵測到的裝置
bass devices

# 3) 從範例設定建立你自己的設定
cp configs/config.example.yaml configs/config.yaml
cp configs/tasks.example.yaml  configs/tasks.yaml

# 4) 用截圖工具建立你自己的模板（每次遊戲改版可能需要重做）
bass capture

# 5) 啟動自動化
bass run --config configs/config.yaml --tasks configs/tasks.yaml
```

## 倉庫結構

```
src/bass/        # 主套件（device / vision / actions / flows / engine / utils）
configs/         # YAML 設定範例
assets/          # 模板圖片與 ROI/threshold 設定
tools/           # 截圖製版、離線回放等開發工具
tests/           # pytest 測試與 fixtures
```

## 設計概觀

詳見原始計畫於 PR 描述。簡述：

- **device** 透過 [`adbutils`](https://github.com/openatx/adbutils) 操作裝置，支援
  截圖、tap、swipe、keyevent，並做解析度標準化。
- **vision** 用 OpenCV 多尺度模板匹配 + 可選 OCR，產生 `SceneState` 列舉。
- **actions** 為「具備前置/後置條件、可重試」的高階動作。
- **flows** 對應劇情/戰鬥/活動三大流程。
- **engine** 主迴圈：截圖 → 偵測場景 → 決策 → 執行 → 驗證。
- **scheduler** 依 `tasks.yaml` 串連多個任務，含全域逾時與安全停止。

## 開發

```bash
pip install -e ".[dev]"
pytest                  # 執行單元測試
ruff check src tests    # 風格檢查
```

## 路線圖（與貢獻）

| 步驟 | 內容 | 狀態 |
| ---- | ---- | ---- |
| 1 | 倉庫骨架 / pyproject / README | ✅ |
| 2 | adb 連線封裝、`bass devices` / `bass screenshot` | ✅ |
| 3 | 視覺模板匹配 + 測試 | ✅ |
| 4 | 截圖製版工具 `tools/capture_template.py` | ✅ |
| 5 | 場景偵測 `state_detector` | ✅ |
| 6 | StoryFlow MVP | ✅ |
| 7 | BattleFlow（倍速/AUTO/出擊/結算） | ✅ |
| 8 | EventFlow / 主線導航 | ✅ |
| 9 | Scheduler / 任務佇列 / 安全停止 | ✅ |
| 10 | replay 工具、文件、QA | ✅ |

實際好用的模板資產（按鈕截圖）需由使用者依自己的解析度與服務區自行採集，
專案提供 `bass capture` 工具協助。

## 授權

MIT
