"""人工介入提示。

設計約定 (見使用者回饋):
- 一般日誌一律英文。
- 唯獨『需要人工介入 / 任務結束需手動接續』這類提示, 以本地化語言 (中文) +
  顏色標準輸出, 讓使用者一眼注意到。
"""
from __future__ import annotations

import sys

_RED = "\033[1;91m"
_YELLOW = "\033[1;93m"
_GREEN = "\033[1;92m"
_RESET = "\033[0m"

# 本地化提示文案 (僅此處本地化)。
_MESSAGES = {
    "network": (_RED, "⚠ 需要人工介入：網路重連多次仍失敗，請手動檢查網路後重試。"),
    "stuck": (_RED, "⚠ 需要人工介入：長時間未偵測到可操作元素，可能卡住，請手動排查。"),
    "combat_lost_home": (_RED, "⚠ 需要人工介入：戰鬥失敗並退回首頁，請手動處理後重試。"),
    "mobilize_stall": (_RED, "⚠ 需要人工介入：出擊隊伍可能為空或無法開始戰鬥，請手動編成隊伍後重試。"),
    "chapter_done": (_GREEN, "✓ 本章全部關卡已完成，任務結束。請手動進入下一章後重新執行。"),
    "momotalk_done": (_GREEN, "✓ MomoTalk 已無未讀，好感劇情任務結束。"),
}


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def enable_windows_ansi() -> None:
    """在 Windows 主控台啟用 ANSI 跳脫序列 (VT 處理)。非 Windows 為無操作。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k = ctypes.windll.kernel32
        # STD_OUTPUT_HANDLE = -11; ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x4
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass


def manual(kind: str) -> None:
    """印出一則本地化、上色的人工介入/結束提示。kind 不在表中時原樣輸出。"""
    color, text = _MESSAGES.get(kind, (_YELLOW, kind))
    if _supports_color():
        print(f"\n{color}{text}{_RESET}\n", flush=True)
    else:
        print(f"\n{text}\n", flush=True)
