# 地圖生成與 Solver 優化研究

更新日期：2026-06-12

## 研究目標

本次改造同時處理兩個問題：

1. 保留最短解保證，但大幅降低單一目標與地圖候選的解算時間。
2. 不再只修改固定原圖，而是生成可泛化的新盤面；盤面需具輕度對稱、牆壁不群聚。
3. Hard 不只驗證前五題，而是控制完整 17 題的難度曲線，避免第 6、7 題後步數與使用機器人數突然下降。

## 改造前演算法

### Solver

原本的 `RicochetSolver.solve()` 是完整 labeled BFS：

- 狀態是依顏色排序的所有機器人座標 tuple。
- 每個狀態最多展開 `機器人數量 x 4` 個動作。
- 每次移動都逐格掃描牆壁與其他機器人。
- `visited`、`depth`、`parent` 分別保存大量 Python 物件。
- 沒有啟發式；即使目標已接近，也要逐層展開所有較淺狀態。

這個方法能保證最短解，但深度 8 到 11 的題目容易展開十萬級狀態。

### Generator

原本 Normal / Hard 的生成方式不是建立新盤面，而是：

1. 複製 `ricochet_robots_board_data.py` 的固定牆壁與固定目標。
2. 只在左上、左下象限額外放置 1 到 6 個 L 型牆。
3. 對抽樣目標執行一次 BFS。
4. 再對其他目標重複 BFS，收集至少 8 個可解目標。
5. 所有目標都從同一組初始機器人位置解算。

因此它有三個結構性問題：

- 新地圖仍高度接近固定原圖，變化主要集中在局部。
- 同一候選、同一目標可能被重複解算。
- 「多個目標可從初始狀態解出」不等於「解完上一題後，可從新的機器人狀態繼續完成下一題」。

## 基準結果

環境：Python 3.10.8、本專案 venv、Windows。

| 項目 | 改造前 | 改造後 |
|---|---:|---:|
| 固定盤面 `Yellow_Star`，10 步 | 約 3.62 秒 | 約 0.66 秒 |
| 固定盤面 `Blue_Gear` | 220,000 states 內未找到 | 約 0.95 秒找到 11 步最短解 |
| Normal，完整 17 回合認證 | 不適用 | 離線認證後約 0.03 秒載入；目前每題 6–9 步、至少 2 台機器人 |
| Hard，舊版前五題 `n=9, m=3` | 約 14.28 到 18.11 秒 | 平均 11.20 秒，但第 6 題後未受保護 |
| Hard，完整 17 題 `n=9, m=3` 認證 | 不適用 | 12 張基底、4 種拓樸家族；約 0.03–0.05 秒建立，步數 9 到 13、每題至少 3 台機器人 |

改造後另外以 12 組隨機狀態，將新 A* 與原 labeled BFS 交叉比對；所有可解、不可解與最短步數結果一致。

## 文獻比較

| 論文 | 年份 / 來源 | 核心方法 | 對本專案的意義 | 限制 |
|---|---|---|---|---|
| Hula et al., *Fast Heuristic for Ricochet Robots* | 2023, ICAART | 用 robot interaction subgoals、reachability graph 與 lower-bound pruning 搜尋受限解空間 | 直接證明 Ricochet Robots 可利用 relaxed reachability 與下界大幅減少搜尋 | 保證的是受限解空間內最短解；完整實作較複雜 |
| Gouveia et al., *Logic-Based Encodings for Ricochet Robots* | 2017, EPIA | 將固定步數解編碼成 SAT，逐步增加或二分步數求最佳解 | 適合離線批次與嚴格最佳化，也證明 incremental reuse 有效 | 需要額外 SAT solver，整合與打包成本較高 |
| Hesterberg and Kopinsky, *The Parameterized Complexity of Ricochet Robots* | 2017, Journal of Information Processing | 證明此類 sliding puzzle 的參數化複雜度下界 | 說明不能期待單靠一般 BFS 在所有盤面都有效 | 複雜度研究，不提供 runtime generator |
| Smith and Mateas, *Answer Set Programming for Procedural Content Generation* | 2011, IEEE TCIAIG | 以宣告式 hard/soft constraints 明確描述 design space | 支持將「可玩、牆密度、對稱、間距」寫成顯式生成約束 | 需要 ASP solver；runtime 與部署成本不適合目前小型 Python 專案 |
| Togelius et al., *Search-Based Procedural Content Generation* | 2011, IEEE TCIAIG | 用搜尋或最佳化探索內容空間，fitness 評估品質 | 適合把 difficulty、symmetry、clutter、playability 分開量化 | 若每個候選都做昂貴 playtest，成本會很高 |
| Horswill and Foged, *Fast Procedural Level Population with Playability Constraints* | 2012, AIIDE | 先以 constraint propagation 排除不可能候選，再做較昂貴驗證 | 支持本次「廉價結構檢查先行，精確 solver 最後執行」的分層流程 | 原論文是室內關卡物件配置，不是 Ricochet Robots |
| O'Sullivan and Horan, *Generating and Solving Logic Puzzles through Constraint Satisfaction* | 2007, AAAI | 同時控制可解性、分級難度與視覺對稱 | 支持把難度與美觀視為共同約束，而非生成後才補救 | 研究對象不是連續狀態的多回合滑行棋盤 |
| Khalifa et al., *Intentional Computational Level Design* | 2019, GECCO | 用 simulation-based constraints 與 quality diversity 尋找符合設計意圖的內容 | 支持以完整遊玩軌跡評分地圖，而不是只看單題 | 完整演化搜尋適合離線，不適合每次進模式即時計算 |
| Beukman et al., *Towards Objective Metrics for Procedurally Generated Video Game Levels* | 2022, arXiv | 以代理軌跡、搜尋成本與行為特徵衡量難度與多樣性 | 支持同時記錄步數、使用機器人數與搜尋展開量 | 指標仍需依實際遊戲規則校準 |
| González-Duque et al., *Finding Game Levels with the Right Difficulty in a Few Trials* | 2020, CoG | 用 intelligent trial-and-error 尋找指定難度區間 | 支持將昂貴難度搜尋移到離線，再保存可重用結果 | 需要維護行為描述與離線 archive |
| Gravina et al., *Procedural Content Generation through Quality Diversity* | 2019, IEEE CoG | 同時追求品質與行為特徵空間覆蓋 | 適合未來保留不同難度、密度、對稱度的多張候選，而非只找單一最高分地圖 | 完整 MAP-Elites 對目前即時生成需求偏重 |
| Bazzaz and Cooper, *Level Generation with Constrained Expressive Range* | 2025, FDG | 在 density / difficulty expressive range 中系統選擇欠代表區域，再由 constraint generator 產生 | 支持以明確 metrics 控制可泛化地圖類型，而不是盲目 random | 實驗對象是 tile platformer，部分指標不可直接移植 |

## 採用的演算法

### 1. Exact Canonical A*

Classic、無斜牆模式使用新的精確 A*：

- 座標編碼成單一整數。
- 預計算每格四方向的靜態滑行 ray。
- 目標機器人保留身份；其他同質 helper robots 依位置排序 canonicalize。
- Wild 目標可將所有機器人 canonicalize。
- heuristic 是「忽略其他機器人，並允許沿無牆直線任意停止」的 relaxed rook distance。

此 relaxation 比真實規則更寬鬆，因此是 admissible lower bound；A* 仍保證回傳最短步數。斜牆與 Momentum 因顏色或連鎖移動會影響轉移，仍走 labeled BFS，避免錯誤合併狀態。

### 2. Structured Motif Generation

新生成器不是逐牆獨立 random，而是使用結構化 motif：

1. 從多組 quadrant template 選擇 L-wall anchor 分布。
2. 將 template 映射到四象限，形成可辨識的旋轉節奏。
3. 以受控 orientation mutation 打破完全對稱。
4. 加入成對邊緣 notch 與固定中央障礙。
5. 將 16 個彩色目標平均分配到四象限，再放置 Wild 目標。
6. 每個主要機器人分散到不同象限。
7. Normal 使用約 50 面牆；Hard 基底使用約 62 面牆與 Silver 機器人。

生成流程依成本排序：

1. 目標間距、象限平衡、旋轉對稱度。
2. 牆段 connected component 大小，限制牆壁黏成大團。
3. relaxed reachability 預檢。
4. Exact A* 從當前機器人狀態解題、回放路徑，再從新的終局狀態解下一題。
5. 檢查精確最短解的步數、相鄰回合降幅與實際移動過的不同機器人數。
6. Normal 完整 17 題目前為 6–9 步，每題移動至少 2 台機器人。

### 3. Hard Full-Session Planner

問題重現顯示，舊版只替前五題保存 `validated_target_order`；第六題後只排除 3 步以下目標。三張測試地圖都在第 6 到 8 題附近降到 1 台機器人與 2 到 5 步，因此不是參數偶發，而是驗證範圍不足。

離線 Hard 規劃器採用：

1. 從盤面所有 L 型牆角與邊界牆角選擇目標位置，不再受原本 17 個 anchor 限制。
2. 預先安排平衡顏色序列：四色各出現 4 次、Wild 出現 1 次，避免尾段只剩難以配置的單一顏色。
3. 對每個候選位置執行 exact canonical A*，只接受最短步數 `n>=9` 且該最短路徑移動機器人數 `m>=3` 的候選。
4. 使用 depth-first search 與 backtracking 保留替代位置，前一選擇讓後續顏色無解時立即回溯。
5. 完整 17 題皆需通過 `n=9, m=3`；目前基底平均 9.94 步，範圍 9 到 13 步，最大相鄰下降 3 步。

完整搜尋雖能得到合格盤面，但不同 seed 可能耗費數十秒到數分鐘，因此不放在玩家切換模式的即時路徑。

### 4. Offline Catalog + Exact Symmetry Variants

正式 Hard 模式改採離線認證目錄：

1. 保存已通過 `9/3 x 17` 驗證的牆、目標、起始位置、順序與精確最短路徑。
2. 執行時套用已通過 exact A* `m>=3` 驗證的幾何變換、四顏色置換與四形狀置換。
3. 路徑方向與機器人顏色同步轉換，因此轉換前後是嚴格圖同構，最短步數與使用機器人數不變。
4. 幾何同構雖保留最短步數，但 A* 在同長替代解之間的 tie-breaking 可能改變 `m`；因此只啟用重新求解後仍穩定為 `m>=3` 的原向與水平鏡射。
5. `assets/map_catalog_v2.json` 目前保存 12 張 Hard 基底，分成 `balanced_rooms`、`offset_pinwheel`、`axial_gates`、`central_locks` 四個家族。
6. 認證變體約 0.03–0.05 秒完成重放與品質資料建立。
7. Smoke test 會逐題重新執行 exact A*，確認保存路徑長度等於真正最短步數，並確認 solver 回傳的最短路徑至少使用 3 台機器人。

結果會保存：

- `validated_target_order`
- 每回合的最短步數與 path
- 每回合的 `moved_robots` 與 `moved_robot_count`
- 每回合終局機器人位置
- symmetry、wall cluster、spacing、總步數等品質指標

`GameEngine.load_generated_board()` 會優先使用完整已驗證順序。若玩家採用不同解法，使下一題低於 Hard 的步數或機器人門檻，引擎會往後尋找仍符合門檻的未完成目標。

## 2026-07-03：Endpoint 設計器效能改造、泛用性驗證與替代演算法評估

（本章對應 endpoint-targeting inverse design 上線後的第一次全面體檢。）

### 1. 泛用性壓測（`scripts/stress_test_endpoint_designer.py`）

驗證題目：這個「把目標點當設計輸出」的反向建構器，是否只在出貨的板面與難度帶上剛好可用，還是真正泛用？

測試矩陣：4 張板 ×6 條難度帶，其中 2 張板是**隨機結構突變板**（隨機拆牆＋隨機補 L 牆，只要求通過結構檢查），4 條帶是**沒有任何模式使用過的自訂帶**（4–7/r2、7–11/r3、10–14/r3、以及 min_robots=4 的極端帶 8–12/r4）。

結果：**24/24 全數產出完整 17 題認證鏈式 session**（每題皆經 exact re-solve 驗證在帶內、機器人數達標）。Momentum endpoint 規劃器另測 3 張板（hard 基底、對稱 Normal seed、隨機突變板）× 2 組隨機起點 = **6/6 全過**（每題 6–12 步、每題至少一次動量碰撞）。結論：設計器對板面與難度帶皆是參數化泛用的；唯一的內建假設是 grid_size ≤ 16（位元打包）。

### 2. 效能改造（`session_planner._endpoints`，佔規劃時間約九成）

改造前熱點：每次 BFS 對 1,200 萬次 `get_slide_endpoint` 呼叫逐格掃牆。改造內容：

1. 狀態改為單一整數（每台機器人一個 byte），visited 改為集合（FIFO BFS 深度單調，首次到訪即最短）。
2. 滑行改為 O(1) 位棋盤運算：預先建好每個（格, 方向）的射線遮罩、無阻擋終點與步幅；`遮罩 ∩ 佔用位棋盤` 後用最低／最高位元直接得到第一個阻擋者。

以 JSON 全文比對驗證**輸出與舊版逐位元相同**（同 seed 同 plan），加速 2.5–3.1 倍：Normal 約 36s→12s、Hard 約 93s→37s。Momentum 規劃（約 170–190s）刻意不動：其成本在 `resolve_momentum_move`（遊戲共用規則碼，改動風險高），且屬一次性離線建目錄成本。

### 3. 替代演算法評估：不用反向建構行不行？

**反向走步（backward walk / pre-image 枚舉）原型**：數學上，一台停在 E、方向 m 的機器人，其合法出發格是沿 −m 方向、走廊無牆無機器人的任意格（且 E 需滿足停止條件）。從「目標已達成」狀態反向走 k 步可得一個「最短解 ≤ k」的起始盤面，再用 exact solver 驗證帶內。實測（同板同帶）：

- Normal 帶：每產出 1 題認證需 0.93 秒；endpoint BFS 一次搜尋 0.97 秒同時產出 468 個帶內選項（每題攤提 2.1 ms）——約 **450 倍差距**。
- Hard 帶：240 秒、2,400 萬次走步嘗試，**0 題**通過。原因：隨機反向走步幾乎必然存在捷徑（真實最短 << k），而隨機終局盤面極少天然承載 9–13 步最短解。
- 結構性缺陷：反向走步落點是隨機起始盤面，**無法銜接前一回合的終局狀態**，因此無法維持 17 題鏈式接續——這正是 endpoint 正向 BFS 的形狀優勢（起點固定、終點自由）。

**其他選項**：CP/SAT 宣告式合成（文獻中用於證明/求解，狀態爆炸使其只適合離線認證器）；meet-in-the-middle 雙向搜尋（若未來要認證 15+ 步超長帶可再評估）；ML 難度預測（無保證，只能當預過濾）。結論：對「固定起點、鏈式、帶內認證」這個問題形狀，endpoint 反向建構在數學上就是對的分解方式，實測也全面勝出，維持現行方法。

## 目前限制與後續方向

- 17 回合證明對應 catalog 保存的精確最短路徑終局；玩家使用不同解法時會自適應跳到仍符合門檻的後續目標，但不能數學保證所有可能終局都存在相同的完整曲線。
- `m` 表示 solver 回傳的精確最短解實際移動過幾種不同機器人；目前不額外證明不存在另一條使用較少機器人的同長替代解。
- Easy 維持原本固定棋盤，不使用此生成流程。
- Expert 的彩色斜牆會使 helper robots 不再同質，因此不能使用相同 canonicalization。
- catalog 已擴充為 12 張 Hard 基底與四個拓撲家族；後續新增盤面仍應使用離線 exact 驗證，不把昂貴搜尋放回即時流程。
- 未來若要建立大量風格不同的地圖庫，可在現有品質 metrics 上加入 MAP-Elites archive。
- 若未來允許新增原生依賴，可另外評估 SAT backend 作為離線高難度地圖認證器。

## 來源

- Hula, Adamczyk, Janota (2023): https://doi.org/10.5220/0011699900003393
- Gouveia, Monteiro, Manquinho, Lynce (2017): https://doi.org/10.1007/978-3-319-65340-2_54
- Hesterberg, Kopinsky (2017): https://doi.org/10.2197/ipsjjip.25.716
- Smith, Mateas (2011): https://doi.org/10.1109/TCIAIG.2011.2158545
- Togelius, Yannakakis, Stanley, Browne (2011): https://doi.org/10.1109/TCIAIG.2011.2148116
- Horswill, Foged (2012): https://cdn.aaai.org/ojs/12511/12511-52-16033-1-2-20201228.pdf
- O'Sullivan, Horan (2007): https://cdn.aaai.org/AAAI/2007/AAAI07-361.pdf
- Khalifa et al. (2019): https://arxiv.org/abs/1904.08972
- Beukman et al. (2022): https://arxiv.org/abs/2201.10334
- González-Duque et al. (2020): https://arxiv.org/abs/2005.07677
- Gravina et al. (2019): https://doi.org/10.1109/CIG.2019.8848053
- Bazzaz, Cooper (2025): https://doi.org/10.1145/3723498.3723845
