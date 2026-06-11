# Ricochet Robots Agent 說明

## 用途

此 repository 是 Ricochet Robots 的 Python / PyQt6 版本，主要工作範圍是 GUI、遊戲邏輯、地圖生成、solver、資源整理與 PyInstaller 打包。

在此 repo 中工作時，請優先遵守以下原則：

- 保持 Python 版本可直接執行與打包
- 不把 exe、zip、build cache、虛擬環境或大型開發素材提交到 Git
- 修改 GUI 時維持繁體中文介面文字
- 變更 solver / generator 後要做基本語法檢查與小型 smoke test

## 語言使用說明

和使用者溝通、撰寫 README / AGENT / 專案說明時，使用繁體中文。程式碼 identifier 維持英文；註解只在有助於理解複雜邏輯時加入，中文或英文皆可，但 GUI 顯示文字應使用繁體中文。

## 執行環境

### Python 環境

此專案使用 **Python 3.10**（本機驗證版本 3.10.8）與本機 venv。全新 clone 後需先建立環境：

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

從 repo 根目錄執行 Python 相關工作時，優先使用：

```powershell
.\venv\Scripts\python.exe
```

開發執行：

```powershell
.\venv\Scripts\python.exe main_gui.py
```

語法檢查：

```powershell
.\venv\Scripts\python.exe -m py_compile main_gui.py game_engine.py solver.py board_generator.py momentum_rules.py ricochet_robots_board_data.py scripts\precalculate_super_expert.py
```

打包：

```powershell
.\venv\Scripts\pyinstaller.exe RicochetRobots.spec
```

### 中文字元編碼

PowerShell 中若要執行會輸出中文的腳本，先設定 UTF-8：

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

讀寫文字檔時明確指定 `encoding="utf-8"`。

### 套件管理

- 不要在未取得使用者確認時自行 `pip install` 或 `conda install`
- 不要假設系統 Python 可用；優先使用 `.\venv\Scripts\python.exe`
- 若 venv 缺少套件，先回報缺少的套件與需要的安裝指令

## Repository 結構

- `main_gui.py`：PyQt6 GUI 入口與主要 UI 流程
- `game_engine.py`：棋盤狀態、移動、撤銷、存檔與勝利判定
- `board_generator.py`：Normal / Hard / Expert 地圖生成
- `solver.py`：BFS 最短解答器
- `ricochet_robots_board_data.py`：固定棋盤資料與棋盤矩陣建構
- `momentum_rules.py`：Momentum (v3) 模式規則與動量傳遞邏輯，設計見 `docs/v3_momentum_design.md`
- `assets/`：正式執行與打包會使用的資源，會被 PyInstaller 打進 exe
- `scripts/`：輔助腳本，例如 Super Expert 預生成地圖（`precalculate_super_expert.py`）與牆面編輯器（`wall_editor.py`）
- `tests/`：基本 smoke test（GUI 建構、地圖生成、momentum 規則）
- `docs/`：設計或系統說明文件（含 `v3_momentum_design.md`）
- `packaging/`：歷史或備用打包設定。`packaging/legacy/RicochetRobots_UI_Test.spec` 為早期 UI 測試用的舊 spec，僅作歷史保留，正式打包請用根目錄的 `RicochetRobots.spec`
- `dev_assets/`：本機開發素材與舊素材，已被 `.gitignore` 忽略
- `release_assets/`：本機保存的 exe / zip 發行檔，已被 `.gitignore` 忽略

## Git 與大型檔案規則

- 不要提交 `build/`、`dist/`、`release_assets/`、`dev_assets/`、`venv/`
- 不要提交 `.exe`、`.zip`、`.pkg`、`.dll` 等打包產物
- 正式可下載的 Windows exe 應放到 GitHub Releases，不要放進 repository tree
- `assets/` 是正式遊戲資源；移動或刪除前必須確認 `main_gui.py` 與 `RicochetRobots.spec` 的路徑仍正確

## 開發注意事項

- `resource_path()` 同時支援一般執行與 PyInstaller `_MEIPASS`，新增資源時要走相同模式
- `RicochetRobots.spec` 目前會把整個 `assets/` 打包進 exe
- PyInstaller 若出現 `PermissionError`，通常是 `dist/RicochetRobots.exe` 仍被 Windows 鎖住，先關閉執行中的 exe
- GUI 中文亂碼通常直接在 `main_gui.py` 對應區塊修正，不要用猜測式批次替換
- Solver 或 generator 牽涉效能與正確性，修改後至少跑語法檢查與小型 scripted check

## 建議檢查

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

地圖生成 smoke test：

```powershell
@'
from board_generator import BoardGenerator
for mode in ['normal', 'hard']:
    updates = []
    result = BoardGenerator().generate(mode, max_attempts=3, progress_callback=updates.append)
    print(mode, bool(result), updates[-1] if updates else None)
updates = []
result = BoardGenerator().generate_expert(max_attempts=3, progress_callback=updates.append)
print('expert', bool(result), updates[-1] if updates else None)
'@ | .\venv\Scripts\python.exe -
```
