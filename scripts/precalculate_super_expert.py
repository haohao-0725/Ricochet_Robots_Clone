"""
precalculate_super_expert.py
=============================
預先生成 3 張 Super Expert (32x32) 的地圖，並儲存為 assets/super_expert_maps.json。

執行方式：
  python scripts/precalculate_super_expert.py

生成條件：
  - 32x32 格地圖
  - 5 顆機器人（含 Silver）
  - 4 面彩色斜向牆壁
  - BFS 驗證最短解 ≥ 10 步
"""

import sys, os, random, json, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ricochet_robots_board_data import build_board_matrix_from_walls
from solver import RicochetSolver

GRID_SIZE = 32
NUM_MAPS = 3
MIN_STEPS = 10
DIAG_COLORS = ['Red', 'Blue', 'Green', 'Yellow']
DIRECTION_DELTAS = {
    'top': (-1, 0),
    'bottom': (1, 0),
    'left': (0, -1),
    'right': (0, 1),
}
DIAGONAL_REFLECTIONS = {
    '/': {
        'top': 'right',
        'bottom': 'left',
        'left': 'bottom',
        'right': 'top',
    },
    '\\': {
        'top': 'left',
        'bottom': 'right',
        'left': 'top',
        'right': 'bottom',
    },
}


def can_enter_diagonal_cell(board, cell, direction, grid_size):
    r, c = cell
    dr, dc = DIRECTION_DELTAS[direction]
    prev_r, prev_c = r - dr, c - dc
    if prev_r < 0 or prev_r >= grid_size or prev_c < 0 or prev_c >= grid_size:
        return False
    return not board[prev_r][prev_c][direction]


def safe_diagonal_types(board, cell, grid_size):
    r, c = cell
    safe_types = []
    for w_type, reflections in DIAGONAL_REFLECTIONS.items():
        safe = True
        for in_direction, out_direction in reflections.items():
            if can_enter_diagonal_cell(board, cell, in_direction, grid_size) and board[r][c][out_direction]:
                safe = False
                break
        if safe:
            safe_types.append(w_type)
    return safe_types


def random_walls_32(grid_size=32):
    """生成 32x32 的隨機 L 型牆壁（防止密室）。"""
    wc = [[0] * grid_size for _ in range(grid_size)]
    for i in range(grid_size):
        wc[0][i] += 1; wc[grid_size-1][i] += 1
        wc[i][0] += 1; wc[i][grid_size-1] += 1

    h_walls = set()
    v_walls = set()

    def add_h(r, c):
        if (r, c) in h_walls: return True
        if r < 0 or r >= grid_size - 1: return False
        if wc[r][c] >= 2 or wc[r+1][c] >= 2: return False
        h_walls.add((r, c)); wc[r][c] += 1; wc[r+1][c] += 1
        return True

    def add_v(r, c):
        if (r, c) in v_walls: return True
        if c < 0 or c >= grid_size - 1: return False
        if wc[r][c] >= 2 or wc[r][c+1] >= 2: return False
        v_walls.add((r, c)); wc[r][c] += 1; wc[r][c+1] += 1
        return True

    # 中央 2x2 障礙物（座標 15,16）
    cx = grid_size // 2 - 1
    for r, c in [(cx, cx), (cx, cx+1), (cx+2, cx), (cx+2, cx+1)]:
        add_h(r, c)
    for r, c in [(cx, cx), (cx+1, cx), (cx, cx+2), (cx+1, cx+2)]:
        add_v(r, c)

    # 邊緣卡榫（等比例放大：原本 4 個，現在 8 個）
    for _ in range(8):
        add_v(0, random.randint(1, grid_size-2))
        add_v(grid_size-1, random.randint(1, grid_size-2))
        add_h(random.randint(1, grid_size-2), 0)
        add_h(random.randint(1, grid_size-2), grid_size-1)

    # L 型牆壁（等比例放大：原本 25~35 個，現在 55~75 個）
    num_l = random.randint(55, 75)
    l_positions = []
    attempts = 0

    while len(l_positions) < num_l and attempts < 2000:
        attempts += 1
        r, c = random.randint(1, grid_size-2), random.randint(1, grid_size-2)
        if r in [cx, cx+1] and c in [cx, cx+1]:
            continue
        ori = random.randint(1, 4)
        if ori == 1: th, tv = (r-1, c), (r, c-1)
        elif ori == 2: th, tv = (r-1, c), (r, c)
        elif ori == 3: th, tv = (r, c), (r, c-1)
        else: th, tv = (r, c), (r, c)

        def can_h(hr, hc):
            if (hr, hc) in h_walls: return True
            if hr < 0 or hr >= grid_size-1: return False
            return wc[hr][hc] < 2 and wc[hr+1][hc] < 2

        def can_v(vr, vc):
            if (vr, vc) in v_walls: return True
            if vc < 0 or vc >= grid_size-1: return False
            return wc[vr][vc] < 2 and wc[vr][vc+1] < 2

        if can_h(*th):
            added_h = False
            if th not in h_walls:
                h_walls.add(th); wc[th[0]][th[1]] += 1; wc[th[0]+1][th[1]] += 1
                added_h = True
            if can_v(*tv):
                if tv not in v_walls:
                    v_walls.add(tv); wc[tv[0]][tv[1]] += 1; wc[tv[0]][tv[1]+1] += 1
                l_positions.append((r, c))
            elif added_h:
                h_walls.remove(th); wc[th[0]][th[1]] -= 1; wc[th[0]+1][th[1]] -= 1

    return h_walls, v_walls, l_positions


def random_targets_32(l_positions, grid_size=32, num_targets=17):
    """從 L 型牆壁位置中隨機挑 17 個格子作為目標點，並命名。"""
    cx = grid_size // 2 - 1
    forbidden = {(cx, cx), (cx, cx+1), (cx+1, cx), (cx+1, cx+1)}
    target_names_template = [
        'Red_Moon', 'Red_Planet', 'Red_Star', 'Red_Gear',
        'Blue_Moon', 'Blue_Planet', 'Blue_Star', 'Blue_Gear',
        'Green_Moon', 'Green_Planet', 'Green_Star', 'Green_Gear',
        'Yellow_Moon', 'Yellow_Planet', 'Yellow_Star', 'Yellow_Gear',
        'Wild_Vortex'
    ]
    avail = [p for p in l_positions if p not in forbidden]
    while len(avail) < num_targets:
        r, c = random.randint(1, grid_size-2), random.randint(1, grid_size-2)
        if (r, c) not in forbidden and (r, c) not in avail:
            avail.append((r, c))

    random.shuffle(avail)
    return {name: avail[i] for i, name in enumerate(target_names_template)}


def random_robots_32(target_pos, diagonal_cells, grid_size=32):
    """隨機放置 5 顆機器人，避開目標與斜牆格子。"""
    cx = grid_size // 2 - 1
    forbidden = {(cx, cx), (cx, cx+1), (cx+1, cx), (cx+1, cx+1),
                 target_pos} | set(diagonal_cells)
    colors = ['Blue', 'Yellow', 'Green', 'Red', 'Silver']
    robots = {}
    for col in colors:
        while True:
            r, c = random.randint(0, grid_size-1), random.randint(0, grid_size-1)
            if (r, c) not in forbidden and (r, c) not in robots.values():
                robots[col] = (r, c)
                break
    return robots


def generate_one_super_expert_map():
    """生成一張 Super Expert 地圖（保證 BFS 最短解 ≥ MIN_STEPS）。"""
    for attempt in range(1, 10001):
        h_walls, v_walls, l_positions = random_walls_32(GRID_SIZE)
        board = build_board_matrix_from_walls(h_walls, v_walls, grid_size=GRID_SIZE)

        # 隨機 4 面斜向牆壁
        cx = GRID_SIZE // 2 - 1
        forbidden_cells = {(cx, cx), (cx, cx+1), (cx+1, cx), (cx+1, cx+1)}
        diag_candidates = [(r, c) for r in range(2, GRID_SIZE-2)
                           for c in range(2, GRID_SIZE-2)
                           if (r, c) not in forbidden_cells]
        safe_diag_options = [
            (cell, safe_types)
            for cell in diag_candidates
            if (safe_types := safe_diagonal_types(board, cell, GRID_SIZE))
        ]
        if len(safe_diag_options) < 4:
            continue
        chosen_options = random.sample(safe_diag_options, 4)
        chosen_cells = [cell for cell, _ in chosen_options]
        diagonal_walls = {
            cell: {'type': random.choice(safe_types), 'color': DIAG_COLORS[i]}
            for i, (cell, safe_types) in enumerate(chosen_options)
        }

        # 生成目標字典
        targets = random_targets_32(l_positions, GRID_SIZE)

        # 選一個目標驗證
        test_name = random.choice(list(targets.keys()))
        target_color = test_name.split('_')[0]
        target_pos = targets[test_name]

        # 放置機器人
        robots = random_robots_32(target_pos, chosen_cells, GRID_SIZE)

        # BFS 驗證
        solver = RicochetSolver(board, grid_size=GRID_SIZE, diagonal_walls=diagonal_walls)
        h_table = solver._get_h_table(*target_pos, color=target_color)
        if len(h_table) < 80:
            continue
        steps, path = solver.solve(robots, target_color, target_pos,
                                   max_depth=20, max_states=200000)
        if steps < MIN_STEPS:
            continue

        print(f"  ✓ 第 {attempt} 次嘗試成功！最短步數: {steps}")
        return {
            'h_walls': [[r, c] for r, c in h_walls],
            'v_walls': [[r, c] for r, c in v_walls],
            'diagonal_walls': {str(k): v for k, v in diagonal_walls.items()},
            'targets': {name: list(pos) for name, pos in targets.items()},
            'robot_positions': {col: list(pos) for col, pos in robots.items()},
            'solved_steps': steps,
            'difficulty': 'super_expert',
            'grid_size': GRID_SIZE,
        }

    print("  ✗ 超過嘗試次數上限，此張地圖生成失敗。")
    return None


if __name__ == '__main__':
    print(f"開始生成 {NUM_MAPS} 張 Super Expert (32x32) 地圖...")
    maps = []
    for i in range(NUM_MAPS):
        print(f"\n[{i+1}/{NUM_MAPS}] 生成中...")
        m = generate_one_super_expert_map()
        if m:
            maps.append(m)

    out_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'super_expert_maps.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(maps, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成！共生成 {len(maps)} 張地圖，已儲存至 {out_path}")
