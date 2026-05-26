# Ricochet Robots Python Edition

這是 Ricochet Robots 的 Python / PyQt6 版本。專案目前同時保留 Godot 版本資料夾，但日常維護與打包主要針對根目錄的 Python 版。

本 README 是給後續 agent / 維護者看的工作說明，重點是快速理解架構、常見修改點、測試方式與打包流程。

## Current Scope

- Python GUI 入口：`main_gui.py`
- 遊戲邏輯：`game_engine.py`
- 地圖生成：`board_generator.py`
- 最短解答器：`solver.py`
- 固定棋盤資料與繪圖輔助：`ricochet_robots_board_data.py`
- 資源檔：`assets/`
- 打包設定：`RicochetRobots.spec`
- Godot 版本：`GODOT_Version/`，除非使用者明確要求，請不要動。

## Run And Build

開發執行：

```powershell
.\venv\Scripts\python.exe main_gui.py
```

語法檢查：

```powershell
.\venv\Scripts\python.exe -m py_compile main_gui.py game_engine.py solver.py board_generator.py ricochet_robots_board_data.py
```

打包 exe：

```powershell
.\venv\Scripts\pyinstaller.exe RicochetRobots.spec
```

輸出位置：

```text
dist/RicochetRobots.exe
```

注意：Windows 有時會鎖住正在執行或剛啟動過的 exe，導致 PyInstaller 覆寫失敗。打包前先關閉 `RicochetRobots.exe`。目前 `dist/RicochetRobots.old.exe` 是歷史舊檔，使用者表示可以先放著。

## Architecture

### `main_gui.py`

PyQt6 GUI 主檔，包含：

- `MainWindow`：主視窗、按鈕、右側 checklist、存檔/讀檔、難度切換。
- `BoardView`：棋盤繪製、機器人繪製、滑鼠/鍵盤移動、動畫。
- `BoardGeneratorThread`：背景生成 Normal / Hard / Expert 地圖，支援取消。
- `SolverThread`：背景計算最佳解，支援取消與「計算中...」動畫。
- `resource_path()`：兼容開發環境與 PyInstaller `_MEIPASS` 的資源路徑。

常見 GUI 文字修正點：

- 計時器文字在 `init_ui()` 的 Timer UI 區塊。
- 提示面板按鈕在 `toggle_solver_panel()`。
- 生成 overlay 在 `init_ui()` 的 Overlay for generator 區塊與 `start_board_generation()`。
- Super Expert 載入提示在 `start_super_expert()`。

### `game_engine.py`

純遊戲狀態與規則層，負責：

- 棋盤、目標、機器人位置、步數、undo history。
- 難度模式狀態：`easy`、`normal`、`hard`、`expert`、`super_expert`。
- 斜牆反射規則。
- 目標完成與下一目標選擇。
- v3 存檔格式與舊 v1/v2 存檔相容讀取。

目前存檔位置：

```text
%USERPROFILE%/ricochet_robots_save.json
```

v3 存檔是一個 JSON，裡面有五個 difficulty slots。按「存檔」只保存目前難度槽位；切換難度時，如果該難度已有槽位就讀取，沒有才生成新地圖。

### `board_generator.py`

Normal / Hard / Expert 地圖生成器。

目前策略：

- 每次 attempt 都透過 progress callback 回報，例如 `已嘗試 n 次`。
- 支援 `cancel_callback`，GUI 可取消背景生成。
- 不再要求固定前 8 個目標都可解，避免高難度生成卡死。
- 改成收集至少 8 個已驗證可解目標。
- 若完整難度條件未達標，但已有足夠可解目標，會回傳最佳已驗證候選地圖。
- 不使用完全未驗證 fallback 地圖。

重要設定在 `BoardGenerator.CONFIGS`：

- `max_attempts`
- `max_states`
- `sample_targets`
- `verified_solvable_targets`
- `target_min_steps`
- `required_hard_targets`

調高這些值會提升品質，但會增加生成時間。

### `solver.py`

最短解答器，目前是精確 BFS：

- 回傳非負步數時，代表該盤面的最小步數。
- `-1` 表示在指定限制內找不到解。
- `-2` 表示被取消。
- 支援 `max_depth`、`max_states`、`cancel_callback`、`progress_callback`。

狀態 canonical 保留機器人顏色身份，避免在有 Silver 或彩色斜牆時把不同顏色錯誤視為同一狀態。

### `ricochet_robots_board_data.py`

固定 16x16 棋盤資料：

- `TARGETS`
- `HORIZONTAL_WALLS`
- `VERTICAL_WALLS`
- `COLORED_HWALLS`
- `COLORED_VWALLS`
- `build_board_matrix()`
- `build_board_matrix_from_walls()`

Normal / Hard 目前仍基於固定棋盤牆面加變化牆，不是完全從零生成。

## Difficulty Behavior

| Mode | Behavior |
| --- | --- |
| Easy | 固定 16x16 經典棋盤，4 台機器人。 |
| Normal | 固定棋盤上加入少量變化牆，4 台機器人，生成時驗證多個目標可解。 |
| Hard | 更多變化牆，加入 Silver 機器人，生成時驗證多個目標可解。 |
| Expert | 固定 16x16 棋盤 + 彩色斜牆 + Silver，生成時驗證至少 8 個可解目標。 |
| Super Expert | 從 `assets/super_expert_maps.json` 讀取 32x32 預生成地圖。 |

Super Expert 不是即時生成；它讀取預生成 JSON。若要重新產生資料，可使用：

```powershell
.\venv\Scripts\python.exe -X utf8 scripts\precalculate_super_expert.py
```

`scripts/precalculate_super_expert.py` 目前也有部分註解亂碼，但邏輯上會輸出 `assets/super_expert_maps.json`。

## Save / Reset / Admin

- 「存檔」保存目前難度槽位。
- 「讀取」讀目前 active difficulty 或指定難度槽位。
- 切換難度前，如果目前有進度，GUI 會提醒先存檔。
- 按目前所在難度按鈕會詢問是否重新生成該難度新地圖。
- 「破關次數」文字連點 5 下會觸發管理員重置確認。
- 管理員重置會清除五難度槽位、破關次數，並回到 Easy 新局。

## UI Notes

- 左上角 information 按鈕使用 `assets/information.png`，按鈕本身是透明背景。
- 生成 Normal / Hard / Expert 時會顯示 overlay 與「取消生成」按鈕。
- Super Expert 是同步讀取預生成地圖，會先顯示 `Super Expert 地圖載入中...` 的 overlay，但沒有取消按鈕。
- 提示面板內的「計算最佳解」會在背景 thread 跑 solver，期間顯示 `計算中.` / `計算中..` / `計算中...`。
- 若玩家切換盤面或清空提示，舊 solver task 會被取消或結果失效。

## Assets

重要資源：

- `assets/app_icon.ico`：exe icon。
- `assets/information.png`：左上角模式說明 icon。
- `assets/*_robot.png`：機器人圖片。
- `assets/*_moon.png`、`*_planet.png`、`*_star.png`、`*_gear.png`：目標 token。
- `assets/black_hole.png`：Wild target。
- `assets/fifth_robot.png`：Silver robot。
- `assets/super_expert_maps.json`：Super Expert 預生成地圖。

`RicochetRobots.spec` 會把整個 `assets` 資料夾打進 exe。

## Agent Working Rules

維護這個專案時請注意：

- 不要碰 `GODOT_Version/`，除非使用者明確要求。
- 優先改 Python 根目錄檔案。
- 手動改檔用 `apply_patch`。
- 打包前確認 `dist/RicochetRobots.exe` 沒有正在執行。
- 若 PyInstaller 報 `PermissionError`，通常是 exe 被 Windows 鎖住；先關閉相關行程再重試。
- 不要刪除使用者提到要保留的舊 exe。
- GUI 中文文字若出現亂碼，優先在 `main_gui.py` 對應 UI 區塊直接替換成正常中文。
- Solver / generator 變更後，至少跑一次語法檢查與小型 scripted check。

## Suggested Checks After Changes

基本檢查：

```powershell
.\venv\Scripts\python.exe -m py_compile main_gui.py game_engine.py solver.py board_generator.py ricochet_robots_board_data.py
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

生成器快速檢查：

```powershell
@'
from board_generator import BoardGenerator
for mode in ['normal', 'hard']:
    updates = []
    result = BoardGenerator().generate(mode, max_attempts=3, progress_callback=updates.append)
    print(mode, bool(result), updates[-1] if updates else None)
result = BoardGenerator().generate_expert(max_attempts=3, progress_callback=updates.append)
print('expert', bool(result))
'@ | .\venv\Scripts\python.exe -
```

打包：

```powershell
.\venv\Scripts\pyinstaller.exe RicochetRobots.spec
```

## Known Caveats

- 部分舊檔案和舊註解曾經有編碼壞掉的中文；新維護文件以 UTF-8 正常中文重寫。
- Super Expert 的預生成腳本註解仍可能有亂碼，但主遊戲讀取 `assets/super_expert_maps.json` 可用。
- 精確 BFS solver 在大地圖或高難度盤面可能很慢；GUI 版 solver 放在 thread 中並支援取消。
- Normal / Hard / Expert 生成品質與速度是 trade-off；若使用者覺得太慢，優先調整 `BoardGenerator.CONFIGS` 的 `max_attempts`、`max_states`、`verified_solvable_targets`。
- 打包會修改 `build/` 與 `dist/` 產物，這是預期行為。
