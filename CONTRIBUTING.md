# 開發協作規則

歡迎一起開發 Ricochet Robots Python Edition。為了讓多人（與 AI agent）協作時不容易做錯、也不遺失原本的設計概念，請遵守以下規則。

開始之前，請先讀過 [AGENT.md](AGENT.md) —— 裡面有更完整的專案慣例、編碼規則與測試建議。

## 環境設定

本專案使用 **Python 3.10**（本機驗證版本 3.10.8）與本機 venv。

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe main_gui.py
```

不要假設系統 Python 可用；所有指令請走 `.\venv\Scripts\python.exe`。

## 分支與提交

- `main` 為穩定分支，請勿直接在 `main` 上開發功能。
- 從 `main` 開出功能分支，建議命名：
  - `feature/<簡述>`：新功能
  - `fix/<簡述>`：修 bug
  - `chore/<簡述>`：打包、文件、整理
- commit 訊息用簡潔的英文祈使句，例如 `Add momentum collision animation`。
- 開 Pull Request 回 `main`，描述清楚改了什麼、怎麼測。

## 送出前檢查

至少跑過語法檢查與 smoke test（細節見 [AGENT.md](AGENT.md) 與 `tests/`）：

```powershell
.\venv\Scripts\python.exe -m py_compile main_gui.py game_engine.py solver.py board_generator.py momentum_rules.py ricochet_robots_board_data.py

# smoke test：不裝 pytest 也能直接執行
$env:QT_QPA_PLATFORM='offscreen'; .\venv\Scripts\python.exe tests\test_smoke.py
# 若已安裝 pytest（pip install -r requirements-dev.txt）
$env:QT_QPA_PLATFORM='offscreen'; .\venv\Scripts\python.exe -m pytest tests
```

修改 `solver.py` / `board_generator.py` / `momentum_rules.py` 後，務必額外做小型功能驗證，因為它們牽涉正確性與效能。

## 不要提交的東西

`.gitignore` 已涵蓋，但請再次確認不要提交：

- `venv/`、`build/`、`dist/`、`__pycache__/`
- `.exe`、`.zip`、`.dll` 等打包產物 —— 正式發佈一律放 GitHub Releases
- `dev_assets/`、`release_assets/` 等本機素材

## 介面與語言

- GUI 顯示文字維持**繁體中文**。
- 程式碼 identifier 用英文；註解中英文皆可，只在有助於理解複雜邏輯時加入。
- README / AGENT / 設計文件用繁體中文。

## 動到資源時要小心

`assets/` 是正式遊戲資源，會被 PyInstaller 打進 exe。移動或刪除前必須確認 `main_gui.py` 與 `RicochetRobots.spec` 的路徑仍正確。
