# Map Catalog v2

更新日期：2026-07-14

## 目的

`assets/map_catalog_v2.json` 是遊戲正式使用的離線認證地圖庫。昂貴的 A* / BFS
驗證只在開發階段執行；玩家切換模式時只會抽選基底並套用已驗證的幾何、顏色及
目標圖形變換。

## 模式合約

| 模式 | 地圖策略 | 17 回合合約 |
|---|---|---|
| Easy | 固定原始棋盤 | 不生成地圖；目標由短到長漸進 |
| Normal | 認證 catalog | 目前 6–9 步，每題至少 2 台機器人 |
| Hard | 認證 catalog | 9–13 步，每題至少 3 台機器人，相鄰最多下降 3 步 |
| Expert | 認證 catalog + 彩色斜牆 | 17 題 exact BFS；至少 8 題觸發反射，目前為 12 題 |
| Momentum | 認證 catalog + 動量規則 | 17 題 exact BFS；每題 4–13 步、相鄰最多下降 3 步，至少 15 題最短解觸發推撞 |
| Super Expert | 密集認證拓樸（幾何變換） | 9–14 步、至少 3 台機器人，並限制平均切換與支援步數 |
| Chaos | 25×25 認證 catalog + 四種特殊機制 | 17 題 exact BFS；每題 5–11 步且至少觸發一次特殊機制；牆群需通過簡潔度與 witness 功能性門檻 |

## Hard 拓樸庫

Hard 目前有 12 張基礎地圖，四個家族各 3 張：

- `balanced_rooms`
- `offset_pinwheel`
- `axial_gates`
- `central_locks`

每張保存：

- 牆、目標及機器人初始位置
- 完整 17 題順序
- 每題 exact 最短路徑與終局
- 步數、移動機器人、切換次數、支援步數及搜尋展開量
- 對稱分數、牆群聚、牆密度及拓樸／軌跡 signature
- 認證方法、父盤面及安全變換

## 建構與續跑

建構器採原子寫入；每接受一張就更新 catalog，因此中斷後可使用相同命令續跑。

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\venv\Scripts\python.exe scripts\build_map_catalog.py --exact
```

完整重新求解稽核：

```powershell
.\venv\Scripts\python.exe scripts\validate_map_catalog.py --exact
```

只檢查 schema、證明路徑、模式合約與機制統計：

```powershell
.\venv\Scripts\python.exe scripts\validate_map_catalog.py
```

## Momentum 尾段規劃

Momentum 不再使用固定目標順序重播。建構器先以貪婪法排出前段（每題 ≥ 5 步、
≥ 2 台機器人、含推撞、相鄰下降 ≤ 3 步），再對最後數題做帶懲罰的回溯搜尋，
最大化尾段最小步數，避免出現舊版「6→3→2 步」的驟降。會掃描多個種子並挑出
第一個通過完整合約的盤面（min ≥ 4 步、相鄰下降 ≤ 3 步、≥ 15 題含推撞）。

> 註：固定 4 台機器人時，並不存在 17 題全部 ≥ 5 步且每題都含推撞的動量盤面，
> 因此最後 1–2 題可能略為簡單，但已不會驟降至 2–3 步。

## Chaos 牆群簡潔度與功能性

Chaos 將每段水平／垂直牆視為整數格點圖的一條 unit edge；共享端點的牆屬於同一個
connected component。對每個 component 計算牆段數、cycle rank
`μ = E - V + 1`、`branch_excess = Σ max(0, degree-2)`、最大 degree 與最長共線段。

生成器只接受：每群最多 4 段、`μ = 0`、`branch_excess ≤ 1`、最大 degree 3、
最長共線 2 段的配置。因此 L、T 與短折線仍可存在，但封閉小方框、十字、多重分枝、
長主幹與多個 L 疊成的複雜牆塊會在任何 BFS 前被拒絕。

美學門檻通過後仍必須完成原本的 17 回合 exact 認證。另逐一移除整個牆群並重播
certified witness；至少 50% 的牆群必須在移除後令 witness、目標或 Chaos 合約失效。
這是牆群功能性的低成本下界，避免只為填滿 112 段牆而留下大量完全不參與認證解的裝飾。

## 已知限制

- Hard 12 張盤面的牆面拓樸彼此不同（4 家族各 3 張），但因為都由同一個已認證
  的 seed 透過「不影響解答的安全牆」擴增而來，17 題的解答軌跡相同。要產生真正
  不同的解答軌跡需要全新合法盤面，而在現行嚴格合約（每題 9–13 步、≥ 3 台機器
  人、平滑曲線）下，隨機/擾動搜尋幾乎找不到合法盤面，因此暫時維持視覺差異。
- Super Expert 由最密集的 Hard 盤面套用固定幾何變換（旋轉／鏡射）而成，
  拓樸與軌跡 signature 都與所有 Hard 不同，不再是同一筆資料改名；但底層仍是
  同一個 seed 謎題的變換版本，難度差異主要來自更嚴格的平均步數／切換／支援門檻。
- 已淘汰舊版「32x32 且只驗證一題」的 Super Expert 正式載入流程；舊版存檔會被
  視為不相容並自動重新生成最新盤面。
