# Endpoint 反向建構器（Endpoint-Targeting Inverse Design）參考文件

更新日期：2026-07-03
適用讀者：後續接手的 agent 或開發者。讀完本文即可理解、維護、擴充本專案的地圖生成核心，不需要重讀歷史研究記錄。

---

## 1. 要解的問題

生成一張 16×16 Ricochet Robots 地圖，使其完整 **17 個回合**滿足：

- 每回合的**精確最短解**步數落在難度帶 `[lo, hi]` 內（例如 Hard 為 9–13 步）；
- 每回合最短解至少移動 `min_robots` 台不同機器人（Hard 為 3）；
- 回合之間**機器人位置鏈式接續**（上一題的終局就是下一題的起點，**不重置**——這是刻意的遊戲設計，回合之間要互相影響）；
- 相鄰回合步數最多下降 3（`MAX_DROP`）、目標點彼此間隔至少 2 格（`MIN_SPACING`）；
- 每種顏色最多 4 個目標＋1 個 Wild（實體目標配額）。

## 2. 為什麼「正向生成」走不通（歷史結論，不要重試）

以下方法都做過並定量否決，記錄在 `docs/map_generation_solver_research.md`：

| 方法 | 結果 |
|---|---|
| 固定 17 個目標 + 鏈式驗證，換 seed 硬試 | 鏈式狀態演化後必然「飢餓」：最多撐到 ~12/17 題滿足 ≥3 機器人 |
| 增加機器人數量 | 更糟——多一台反而提供更多捷徑，縮短最短解 |
| 加牆拉長最短解（CEGIS/wall forcing） | 加牆常常反而**縮短**最短解（單調性不成立）；且 17 條凍結見證路徑會覆蓋全盤，無牆可加 |
| 反向走步（從終局反向 k 步 + exact 驗證） | Normal 帶每題認證 0.93s（比 endpoint 法慢 ~450 倍）；Hard 帶 240 秒 0 題；且落點無法銜接鏈式起點 |

**核心教訓：把「目標位置」當成固定輸入，這個問題就是欠約束的；把它翻成設計輸出，問題立刻變成建構性的。**

## 3. 核心概念（一句話）

> 從當前鏈式機器人狀態做**一次** labeled BFS 到深度 `hi`，就同時得到「每種顏色到每一格的精確最短步數」；把本回合的目標**放在**一個帶內（`lo ≤ 步數 ≤ hi` 且移動機器人數達標）的終點格上，回合就**依建構保證**合格；沿 BFS parent 還原見證路徑推進機器人，進入下一回合。17 次即得完整認證 session。

沒有加牆、沒有重置、沒有放寬難度——難度是被「選出來」的，不是被「湊出來」的。

## 4. 程式碼地圖

| 檔案 | 內容 |
|---|---|
| `session_planner.py` | 通用設計器 `SessionPlanner`（classic 滑行模式：Normal / Hard / 任意自訂帶） |
| `scripts/build_map_catalog.py` | 目錄建置器；momentum 版設計器（`momentum_endpoints` / `plan_momentum_endpoint_session`）；板面來源（`endpoint_boards`） |
| `mode_contracts.py` | 各模式的可玩性合約（帶、機器人數、降幅……）；`session_planner.MODE_BANDS` 需與其同步 |
| `catalog_validation.py` | 目錄項目的 exact 重驗證 |
| `scripts/validate_map_catalog.py` | 重新驗證整份出貨目錄（`--exact`） |
| `scripts/stress_test_endpoint_designer.py` | 泛用性壓測（多板 × 多帶 × momentum 跨板） |
| `assets/map_catalog_v2.json` | 出貨目錄（18 張認證圖）；執行時只做同構變換，不做線上搜尋 |

## 5. `SessionPlanner` 演算法細節

### 5.1 `_endpoints(config)` — 熱迴圈（約佔 90% 時間）

- 一次 labeled BFS 到深度 `hi`，回傳 `per_colour[顏色][格子] = (精確最短深度, 移動機器人數, 終局狀態鍵)` 與 parent 指標。
- **關鍵正確性細節**：記錄的是該顏色**第一次**（即最短）到達該格的深度——任何深度都記，之後才過濾到 `[lo, hi]`。早期版本只記錄帶內深度，結果把「離開再繞回來」的 9 步繞路誤當成最短（真實最短 5 步），被 exact 驗證抓出。**不要改回去。**
- 效能實作（2026-07-03，輸出與樸素版逐位元相同）：
  - 狀態 = 單一整數，每台機器人一個 byte（`_pack`/`_unpack`；隱含假設 `grid_size ≤ 16`）；
  - 滑行 = O(1) 位棋盤：預建每（格, 方向）的射線遮罩 / 無阻擋終點 / 步幅（`_build_slide_tables`），`遮罩 ∩ 佔用` 後用最低/最高位元取得第一個阻擋者；
  - `visited` 是集合：FIFO BFS 深度單調，首次到訪即最短；
  - 狀態上限 `cap=160000`（超限風險由 `verify()` 兜底）。

### 5.2 `plan(robot_start, rng)` — 回合 DFS + 回溯

- 每層列出所有合格選項（帶內、機器人數達標、未用格、間距、降幅限制、顏色配額 4+1 Wild）；
- 排序偏好：`spread=True` 時先選**最少目標的 4×4 區域**（讓目標散佈全盤；同構保難度不變），再偏好更多機器人、接近帶中點的步數，最後隨機打破平手；
- 每層只展開前 16 個選項（夠用且防爆炸）；死路即回溯。

### 5.3 `verify(robot_start, rounds)` — exact 兜底

用完整 exact solver 逐回合重解，確認「規劃步數 == 真實最短」且機器人數達標、鏈式接續正確。**這一層是 BFS `cap` 的安全網，任何改動都不可移除。**

### 5.4 入口

```python
plan_normal_session(h_walls, v_walls, seed=..., spread=True)   # 帶 (5,9,2)
plan_hard_session(...)                                          # 帶 (9,13,3)
plan_session(h_walls, v_walls, lo, hi, min_robots, ...)         # 任意自訂帶
```

`plan_session` 會嘗試多組隨機機器人起點（`start_attempts`），回傳第一個通過 `verify` 的完整 session（entry-ready dict）。

## 6. Momentum 版（`scripts/build_map_catalog.py`）

同一個思想，換移動規則與額外機制條件：

- `momentum_endpoints()`：labeled momentum BFS（走 `resolve_momentum_move`），對每（顏色, 格）記錄精確最短深度，**並同時追蹤「路徑上是否發生過動量碰撞」**（`coll_reach` / `coll_parent`），使還原出的見證路徑是「最短長度且含碰撞」；
- 碰撞移動天然帶動 ≥2 台機器人，所以機器人數條件自動滿足；
- 合約：每題 6–12 步、17/17 題都需碰撞（`mode_contracts.v3_momentum`）；
- `ensure_momentum_catalog` 在固定板上試多組隨機起點，成功後以 exact momentum solver 認證。

## 6.5 Chaos 版與碰撞終結（2026-07-03 新增，證明第 8 節的擴充指南可行）

**碰撞終結（Momentum 強化）**：`momentum_endpoints` 現在追蹤 `fin_parent`——每個狀態「以碰撞轉移到達」的（前驅, 移動）。目標只放在「最短深度且到達轉移是碰撞、且該回合目標機器人在該轉移中移動」的終點格，於是**每一題最短解的最後一步都是把機器人撞上目標（或撞停在目標上）**。合約欄位 `min_final_collision_rounds: 17`；特徵 `final_move_momentum_collisions` 由 `solver.analyze_path` 回報。

**Chaos 模式（25×25，四機制合一）**：`chaos_rules.py` 合併動量推撞＋斜牆反射＋傳送門（彩色限同色、白色萬用、出口被佔則失效、傳送不耗動量）＋沙格（進入即停、吸收剩餘動量），進格效果順序＝沙格→傳送門→斜牆。設計器樣板照抄 momentum：`chaos_endpoints`（機制旗標＝任一特殊事件）＋ `plan_chaos_endpoint_session`（目標不放特殊格）。25×25 中央 2×2 落在 (11,11)–(12,12)（`grid//2-1..grid//2`，桌面/手機建板函式皆自動處理）。合約：5–11 步、17 題全部至少一次特殊機制、exact 認證。目錄欄位新增 `portals` / `sand_cells`（map_catalog 編解碼、簽章僅在非空時納入以保持舊圖簽章不變）。**手機版規則一致性**：以 400 組隨機移動向量比對 Python `resolve_chaos_move` 與 JS `chaosMove`，400/400 全同。

**Chaos 牆面 grammar（2026-07-14）**：`wall_layout.py` 將 `h(r,c)` 映成格點邊
`((r+1,c),(r+1,c+1))`，將 `v(r,c)` 映成 `((r,c+1),(r+1,c+1))`。
每次加入一組 L 與其 180° 對稱副本時，四段都必須是新牆，且所有 connected component
需滿足 `E≤4`、cycle rank `E-V+1=0`、`Σmax(0,degree-2)≤1`、最大 degree 3、
最長共線段 2。這保留 L／T／短折線，排除封閉 pocket、多分枝與長主幹。牆面通過後
仍走完整 endpoint planning 與 exact 認證；最後以逐 component ablation 重播 witness，
要求至少 50% 的牆群是 witness-critical。正式 clean Chaos 盤面仍為 17 題全 8 步、
17/17 題觸發特殊機制，最大牆群由 8 降到 4，複雜牆群由 6 降到 0。

## 7. 泛用性與效能現況（2026-07-03 實測）

- 泛用性：4 板（含 2 張隨機突變板）× 6 帶（含 4 條未出貨自訂帶、min_robots=4 極端帶）= **24/24**；momentum 3 板 × 2 起點 = **6/6**。設計器對板面與帶都是參數化泛用的。
- 單場認證耗時（優化後）：Normal ~10–12s、Hard ~33–37s、Momentum ~170–190s（皆為**離線建目錄成本**；玩家端零等待——執行時只載目錄做幾何變換＋顏色/形狀重映射）。

## 8. 擴充指南

**新增一條難度帶／新模式（classic 移動）**：在 `mode_contracts.py` 加合約 → `session_planner.MODE_BANDS` 加帶 → `build_map_catalog.py` 加 `ensure_*_catalog` 生成流程 → 目錄重建 → `scripts/validate_map_catalog.py --exact` 全綠。帶的可行範圍實測 4–14 步都可行；`min_robots=4` 也可行。

**新移動規則（照 momentum 的樣板）**：實作規則的 move resolver → 寫 labeled BFS 版 `*_endpoints`（記錄精確最短深度 + 機制觸發旗標與雙 parent 鏈）→ 照抄 `plan_momentum_endpoint_session` 的骨架。**Expert 斜牆注意**：彩色斜牆使機器人不同質，endpoint BFS 仍可用（labeled 本來就不做同質化），但 exact 驗證要用 labeled BFS 而非 canonical A*。

**已知邊界**：
- 位元打包假設 `grid_size ≤ 16`（一格一 byte）；更大棋盤要改打包寬度。
- 目錄→遊戲的變體只用「已驗證安全」的同構變換（`safe_transforms`），因為同長替代解的 tie-break 可能改變機器人數指標。
- 玩家用非認證最短解過關時，鏈式狀態會偏離認證軌跡：極少數情況下一題開局即達成（任意再動一步就過關）。兩平台行為一致，屬已接受的邊界情況。

## 9. 建置與驗證指令

```powershell
# 重建出貨目錄（含 spread）
.\venv\Scripts\python.exe scripts\build_map_catalog.py --spread ...

# 全目錄 exact 重驗證
.\venv\Scripts\python.exe scripts\validate_map_catalog.py --exact

# 泛用性壓測（快速版 / 完整版）
.\venv\Scripts\python.exe scripts\stress_test_endpoint_designer.py --quick
.\venv\Scripts\python.exe scripts\stress_test_endpoint_designer.py

# 設計器自測（跑真 validator）
.\venv\Scripts\python.exe session_planner.py
```

相關文件：`docs/map_generation_solver_research.md`（研究史與否決方案的完整數據）、`docs/map_catalog_v2.md`（目錄格式）、`docs/v3_momentum_design.md`（動量規則）。
