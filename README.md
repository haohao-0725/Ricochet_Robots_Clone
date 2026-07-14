# Ricochet Robots Python Edition

Ricochet Robots 的 Python / PyQt6 桌面版。遊戲包含經典 16x16 棋盤、多種難度、Silver robot、彩色斜牆、Super Expert 預生成地圖、存檔/讀檔，以及最佳解提示功能。

## 下載遊戲

Windows 使用者請到最新 GitHub Release 下載：

- [RicochetRobots.exe](https://github.com/haohao-0725/Ricochet_Robots_Clone/releases/latest/download/RicochetRobots.exe)

GitHub Release 頁面底部會自動出現 `Source code (zip)` 和 `Source code (tar.gz)`。那是 GitHub 自動產生的原始碼壓縮檔，不是遊戲執行檔。只想玩遊戲的話，請下載 `RicochetRobots.exe`。

## 遊戲功能

- Easy：固定 16x16 經典棋盤，4 台機器人。
- Normal / Hard / Expert / Momentum / Super Expert / Chaos：皆改用 `assets/map_catalog_v2.json`
  的離線認證地圖庫；切換模式時抽選已通過 exact A* / BFS 驗證的盤面並套用等價幾何變換，
  不再即時進行昂貴搜尋。各模式的 17 回合難度合約見 `docs/map_catalog_v2.md`。
- Momentum：加入動量推撞規則，最短解多數回合需觸發推撞。
- Super Expert：16x16 密集拓樸（由最難的 Hard 盤面套用幾何變換），較嚴格的平均複雜度門檻。
- Chaos：25x25 棋盤，整合動量、彩色斜牆、傳送門與沙地機制。
- 支援存檔、讀檔、重開目前難度、undo、破關次數統計（舊版不相容存檔會自動重新生成最新盤面）。
- 內建 BFS 最短解答器，可在提示面板計算最佳解。

## 專案結構

```text
.
├── main_gui.py                         # PyQt6 GUI 入口
├── game_engine.py                      # 遊戲狀態、移動規則、存檔邏輯
├── board_generator.py                  # Normal / Hard / Expert 地圖生成
├── solver.py                           # BFS 最短解答器
├── ricochet_robots_board_data.py       # 固定棋盤資料與棋盤矩陣建構
├── momentum_rules.py                   # Momentum (v3) 模式規則與動量傳遞
├── assets/                             # 正式執行與打包會使用的資源
├── scripts/                            # 輔助腳本（super expert 預生成、牆面編輯器）
├── tests/                              # 基本 smoke test
├── docs/                               # 系統說明文件（含 v3 動量設計）
├── packaging/                          # 歷史或備用打包設定
├── RicochetRobots.spec                 # PyInstaller 打包設定
└── AGENT.md                            # 給後續 agent / 維護者的工作規則
```

本機可能另外存在：

- `dev_assets/`：舊素材、參考圖片、製作原檔、Godot 舊版本資料。
- `release_assets/`：本機保存的 exe / zip 發行檔。
- `venv/`：本機 Python 虛擬環境。

這些資料夾已被 `.gitignore` 忽略，不會提交到 GitHub。

## 初次設定

此專案使用 **Python 3.10**（本機驗證版本 3.10.8）與本機 venv。全新 clone 後請先建立環境：

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 開發執行

從 repo 根目錄執行：

```powershell
.\venv\Scripts\python.exe main_gui.py
```

若 PowerShell 顯示中文亂碼，可先設定 UTF-8：

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## 基本檢查

語法檢查：

```powershell
.\venv\Scripts\python.exe -m py_compile main_gui.py game_engine.py solver.py board_generator.py momentum_rules.py ricochet_robots_board_data.py scripts\precalculate_super_expert.py
```

GUI 建構 smoke test：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
@'
import sys
from PyQt6.QtWidgets import QApplication
from main_gui import MainWindow
app = QApplication(sys.argv)
w = MainWindow()
w.close()
print('gui construction passed')
'@ | .\venv\Scripts\python.exe -
```

## 打包 exe

使用 PyInstaller：

```powershell
.\venv\Scripts\pyinstaller.exe RicochetRobots.spec
```

輸出位置：

```text
dist/RicochetRobots.exe
```

打包前請先關閉正在執行的 `RicochetRobots.exe`。Windows 可能會鎖住剛執行過的 exe，導致 PyInstaller 無法覆寫檔案。

產出的 exe / zip 不要提交到 Git。正式發佈時請放到 GitHub Releases。

## `RicochetRobots.spec` 是什麼？

`RicochetRobots.spec` 是 PyInstaller 的打包設定檔。它告訴 PyInstaller：

- 從 `main_gui.py` 開始打包。
- 把整個 `assets/` 資料夾一起放進 exe。
- 排除目前不需要的 PyQt6 WebEngine / PDF 相關模組，減少打包體積。
- 產生無 console 視窗的 Windows GUI 程式。
- 使用 `assets/app_icon.ico` 當 exe 圖示。

平常玩遊戲不需要碰這個檔案；只有要調整打包內容、圖示、輸出方式或排除模組時才需要修改。

## 發佈流程

1. 確認程式可執行並通過基本檢查。
2. 用 `RicochetRobots.spec` 打包 exe。
3. 確認 `.gitignore` 沒有讓 exe / zip 進入 Git。
4. 建立 tag，例如 `v2.6.0`。
5. 在 GitHub Releases 上傳 `RicochetRobots.exe`。
6. Release 說明中提醒玩家下載 exe，不要下載自動產生的 source code 壓縮檔。

## 參與開發

多人協作的分支、PR 與送出前檢查規則放在 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 維護說明

更細的 agent 工作規則、測試建議、Git 大檔案規則與專案慣例放在 [AGENT.md](AGENT.md)。

## 授權

原創程式碼以 MIT 授權，詳見 [LICENSE](LICENSE)。「Ricochet Robots」名稱為其原始權利人所有；本專案為非商業學習用 fan/clone 專案。
