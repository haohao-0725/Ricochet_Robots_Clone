# Ricochet Robots Python Edition

Ricochet Robots 的 Python / PyQt6 桌面版。遊戲包含經典 16x16 棋盤、多種難度、Silver robot、彩色斜牆、Super Expert 預生成地圖、存檔/讀檔，以及最佳解提示功能。

## 下載遊戲

Windows 使用者請到最新 GitHub Release 下載：

- [RicochetRobots.exe](https://github.com/haohao-0725/Ricochet_Robots_Clone/releases/download/v2.6.0/RicochetRobots.exe)

GitHub Release 頁面底部會自動出現 `Source code (zip)` 和 `Source code (tar.gz)`。那是 GitHub 自動產生的原始碼壓縮檔，不是遊戲執行檔。只想玩遊戲的話，請下載 `RicochetRobots.exe`。

## 遊戲功能

- Easy：固定 16x16 經典棋盤，4 台機器人。
- Normal：固定棋盤加少量變化牆，生成時會驗證多個目標可解。
- Hard：更多變化牆，加入 Silver robot。
- Expert：加入彩色斜牆與 Silver robot，生成時驗證至少 8 個可解目標。
- Super Expert：讀取 `assets/super_expert_maps.json` 的 32x32 預生成地圖。
- 支援存檔、讀檔、重開目前難度、undo、破關次數統計。
- 內建 BFS 最短解答器，可在提示面板計算最佳解。

## 專案結構

```text
.
├── main_gui.py                         # PyQt6 GUI 入口
├── game_engine.py                      # 遊戲狀態、移動規則、存檔邏輯
├── board_generator.py                  # Normal / Hard / Expert 地圖生成
├── solver.py                           # BFS 最短解答器
├── ricochet_robots_board_data.py       # 固定棋盤資料與棋盤矩陣建構
├── assets/                             # 正式執行與打包會使用的資源
├── scripts/                            # 輔助腳本
├── docs/                               # 系統說明文件
├── packaging/                          # 歷史或備用打包設定
├── RicochetRobots.spec                 # PyInstaller 打包設定
└── AGENT.md                            # 給後續 agent / 維護者的工作規則
```

本機可能另外存在：

- `dev_assets/`：舊素材、參考圖片、製作原檔、Godot 舊版本資料。
- `release_assets/`：本機保存的 exe / zip 發行檔。
- `venv/`：本機 Python 虛擬環境。

這些資料夾已被 `.gitignore` 忽略，不會提交到 GitHub。

## 開發執行

此專案使用本機 venv。從 repo 根目錄執行：

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
.\venv\Scripts\python.exe -m py_compile main_gui.py game_engine.py solver.py board_generator.py ricochet_robots_board_data.py scripts\precalculate_super_expert.py
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

## 維護說明

更細的 agent 工作規則、測試建議、Git 大檔案規則與專案慣例放在 [AGENT.md](AGENT.md)。
