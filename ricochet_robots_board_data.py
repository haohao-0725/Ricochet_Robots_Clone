# 彈射機器人 (Ricochet Robots) 地圖資料結構
# 座標系統說明：
# 左上角為 (0, 0)，右下角為 (15, 15)。
# 格式為 (row, col) 或稱 (y, x)。

GRID_SIZE = 16

# 目標點字典 (Targets)
# 鍵: (顏色_形狀)
# 值: 座標 (row, col)
TARGETS = {
    # 左上象限 (Top-Left)
    "Yellow_Moon": (1, 2),
    "Blue_Gear": (3, 6),
    "Red_Planet": (5, 4),
    "Green_Star": (6, 1),
    
    # 右上象限 (Top-Right)
    "Green_Planet": (1, 12),
    "Red_Star": (2, 14),
    "Wild_Vortex": (3, 8),    # 多色漩渦
    "Blue_Moon": (5, 9),
    "Yellow_Gear": (6, 11),
    
    # 左下象限 (Bottom-Left)
    "Red_Gear": (8, 5),
    "Blue_Star": (10, 2),
    "Green_Moon": (13, 4),
    "Yellow_Planet": (14, 6),
    
    # 右下象限 (Bottom-Right)
    "Blue_Planet": (9, 12),
    "Yellow_Star": (12, 9),
    "Green_Gear": (13, 14),
    "Red_Moon": (14, 11)
}

# 水平牆壁 (Horizontal Walls)
# (row, col) 代表在格子 (row, col) 的「下方」有一道牆
# 等同於分隔了 (row, col) 和 (row+1, col)
HORIZONTAL_WALLS = {
    # 邊緣向內延伸的卡榫 (Notches)
    (4, 0), (4, 15), (11, 0), (9, 15),
    
    # 中央 2x2 障礙物的外圍 (上下邊緣)
    (6, 7), (6, 8), (8, 7), (8, 8),
    
    (0, 2), (3,6),(4,4),(6,1),(8,5),(0,12),(2,14),(3,8),(5,9),(6,11),(8,12),(9,2),
    (11,9),(12,4),(14,6),(14,11),(13,14)

}

# 垂直牆壁 (Vertical Walls)
# (row, col) 代表在格子 (row, col) 的「右方」有一道牆
# 等同於分隔了 (row, col) 和 (row, col+1)
VERTICAL_WALLS = {
    # 邊緣向內延伸的卡榫 (Notches)
    (0, 4), (0, 10), (15, 4), (15, 13),
    
    # 中央 2x2 障礙物的外圍 (左右邊緣)
    (7, 6), (8, 6), (7, 8), (8, 8),
    
    (1,1),(1,11),(2,13),(3,5),(3,7),(5,4),(5,9),(6,1),(6,11),(8,5),(9,12),(10,2),(12,8),
    (13,3),(13,13),(14,5),(14,11)

}

# 標記顏色的水平牆壁 (Colored Horizontal Walls)
# 鍵: (row, col) - 這裡的座標與 HORIZONTAL_WALLS 定義相同
# 值: 顏色 (如 'red', 'blue', 'green', 'yellow')
COLORED_HWALLS = {
    (8, 7): 'red',    # 範例：將底部 (15, 3) 處的牆面塗紅
    (6, 8): 'yellow'    # 範例：將右側 (4, 15) 處的牆面塗藍
}

# 標記顏色的垂直牆壁 (Colored Vertical Walls)
# 鍵: (row, col) - 這裡的座標與 VERTICAL_WALLS 定義相同
# 值: 顏色
COLORED_VWALLS = {
    (8, 8): 'green',   # 範例：將頂部 (0, 4) 處的牆面塗綠
    (7, 6): 'blue'  # 範例：將頂部 (0, 10) 處的牆面塗黃
}

def build_board_matrix():
    """
    將集合資料轉換為 Agent 尋路演算法容易使用的 2D 陣列 (16x16)。
    每個 Cell 是一個字典，標示四個方向是否被牆壁或邊界阻擋。
    """
    board = [[{'top': False, 'bottom': False, 'left': False, 'right': False} 
              for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
    
    # 1. 處理外圍邊界 (Borders)
    for i in range(GRID_SIZE):
        board[0][i]['top'] = True
        board[15][i]['bottom'] = True
        board[i][0]['left'] = True
        board[i][15]['right'] = True

    # 2. 處理水平牆壁
    for r, c in HORIZONTAL_WALLS:
        if r >= 0 and r < GRID_SIZE - 1:
            board[r][c]['bottom'] = True
            board[r+1][c]['top'] = True

    # 3. 處理垂直牆壁
    for r, c in VERTICAL_WALLS:
        if c >= 0 and c < GRID_SIZE - 1:
            board[r][c]['right'] = True
            board[r][c+1]['left'] = True
            
    # 4. 處理中央 2x2 障礙物內部 (封死內部空間，防止 Agent 邏輯穿透)
    for r in [7, 8]:
        for c in [7, 8]:
            board[r][c] = {'top': True, 'bottom': True, 'left': True, 'right': True}

    return board

def build_board_matrix_from_walls(h_walls, v_walls, grid_size=GRID_SIZE):
    """
    將動態生成的牆壁集合轉換為 Agent 尋路演算法容易使用的 2D 陣列。
    每個 Cell 是一個字典，標示四個方向是否被牆壁或邊界阻擋。
    """
    board = [[{'top': False, 'bottom': False, 'left': False, 'right': False} 
              for _ in range(grid_size)] for _ in range(grid_size)]
    
    # 1. 處理外圍邊界 (Borders)
    for i in range(grid_size):
        board[0][i]['top'] = True
        board[grid_size-1][i]['bottom'] = True
        board[i][0]['left'] = True
        board[i][grid_size-1]['right'] = True

    # 2. 處理水平牆壁
    for r, c in h_walls:
        if r >= 0 and r < grid_size - 1:
            board[r][c]['bottom'] = True
            board[r+1][c]['top'] = True

    # 3. 處理垂直牆壁
    for r, c in v_walls:
        if c >= 0 and c < grid_size - 1:
            board[r][c]['right'] = True
            board[r][c+1]['left'] = True
            
    # 4. 處理中央 2x2 障礙物內部 (封死內部空間，防止 Agent 邏輯穿透)
    center_start = grid_size // 2 - 1
    center_end = grid_size // 2
    for r in [center_start, center_end]:
        for c in [center_start, center_end]:
            board[r][c]['top'] = True
            board[r][c]['bottom'] = True
            board[r][c]['left'] = True
            board[r][c]['right'] = True
            
    return board

def draw_ascii_board(matrix):
    """
    在終端機列印純文字版的 ASCII 地圖，方便快速確認牆壁與目標。
    """
    board_str = ""
    for r in range(GRID_SIZE):
        # 繪製單元格的上邊界
        row_str_top = ""
        for c in range(GRID_SIZE):
            row_str_top += "+"
            if matrix[r][c]['top']:
                c_color = COLORED_HWALLS.get((r-1, c))
                row_str_top += (c_color[0].upper() * 3) if c_color else "---"
            else:
                row_str_top += "   "
        row_str_top += "+\n"
        board_str += row_str_top
        
        # 繪製單元格的左邊界與內容
        row_str_mid = ""
        for c in range(GRID_SIZE):
            if matrix[r][c]['left']:
                c_color = COLORED_VWALLS.get((r, c-1))
                row_str_mid += c_color[0].upper() if c_color else "|"
            else:
                row_str_mid += " "
            
            # 中央障礙物
            if r in [7, 8] and c in [7, 8]:
                row_str_mid += "XXX"
            else:
                # 檢查是否有目標點
                cell_target = "   "
                for target_name, pos in TARGETS.items():
                    if pos == (r, c):
                        parts = target_name.split("_")
                        cell_target = parts[0][0] + parts[1][0] # 例如 Red_Moon 變成 RM
                        break
                row_str_mid += f"{cell_target:^3}"
                
        # 最右側邊界
        if matrix[r][15]['right']:
            c_color = COLORED_VWALLS.get((r, 15))
            row_str_mid += (c_color[0].upper() + "\n") if c_color else "|\n"
        else:
            row_str_mid += " \n"
        board_str += row_str_mid
        
    # 繪製最底部的邊界
    row_str_bot = ""
    for c in range(GRID_SIZE):
        row_str_bot += "+"
        if matrix[15][c]['bottom']:
            c_color = COLORED_HWALLS.get((15, c))
            row_str_bot += (c_color[0].upper() * 3) if c_color else "---"
        else:
            row_str_bot += "   "
    row_str_bot += "+\n"
    board_str += row_str_bot
    print(board_str)

def draw_matplotlib_board(matrix):
    """
    使用 matplotlib 繪製精美的 2D 遊戲地圖。
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches
    except ImportError:
        print("\n[系統提示] 若要觀看精美彩圖視窗，建議安裝 matplotlib： pip install matplotlib")
        return

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')
    ax.set_xlim(0, GRID_SIZE)
    ax.set_ylim(0, GRID_SIZE)
    ax.invert_yaxis() # y軸反轉，讓 (0,0) 在左上角

    # 繪製網格線
    for x in range(GRID_SIZE + 1):
        ax.axvline(x, color='lightgray', linewidth=0.5, zorder=0)
    for y in range(GRID_SIZE + 1):
        ax.axhline(y, color='lightgray', linewidth=0.5, zorder=0)

    # 繪製中央黑框內部區域
    center_rect = patches.Rectangle((7, 7), 2, 2, linewidth=0, facecolor='darkgray', zorder=1)
    ax.add_patch(center_rect)

    # 繪製目標點
    color_map = {
        'Red': 'tab:red', 'Blue': 'tab:blue', 'Green': 'tab:green', 
        'Yellow': '#CCCC00', 'Wild': 'purple'
    }
    for target_name, (r, c) in TARGETS.items():
        color_name, shape_name = target_name.split('_')
        color = color_map.get(color_name, 'black')
        
        # 在格子上標記目標
        ax.text(c + 0.5, r + 0.5, shape_name[:2], 
                color=color, fontsize=11, ha='center', va='center', fontweight='bold',
                bbox=dict(facecolor='white', edgecolor=color, boxstyle='round,pad=0.2', alpha=0.9), zorder=3)

    # 定義繪製牆壁的函式
    def draw_wall(x1, y1, x2, y2, colored_dict, wall_key):
        w_color = colored_dict.get(wall_key)
        if w_color:
            # 彩色牆面畫粗一點並且放在最上層 (zorder=5) 覆蓋黑色
            ax.plot([x1, x2], [y1, y2], color=w_color, linewidth=7, zorder=5)
        else:
            ax.plot([x1, x2], [y1, y2], color='black', linewidth=4, zorder=4)

    # 繪製牆壁 (包含指定的彩色起始牆面) 與格子內部座標
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            cell = matrix[r][c]

            # 上牆對應的是 (r-1, c) 的 horizontal wall
            if cell['top']:
                draw_wall(c, r, c+1, r, COLORED_HWALLS, (r-1, c))
            # 下牆對應的是 (r, c) 的 horizontal wall
            if cell['bottom']:
                draw_wall(c, r+1, c+1, r+1, COLORED_HWALLS, (r, c))
            # 左牆對應的是 (r, c-1) 的 vertical wall
            if cell['left']:
                draw_wall(c, r, c, r+1, COLORED_VWALLS, (r, c-1))
            # 右牆對應的是 (r, c) 的 vertical wall
            if cell['right']:
                draw_wall(c+1, r, c+1, r+1, COLORED_VWALLS, (r, c))
            
            # 在空白格子內淡淡地標示座標，方便對照
            is_center = (r in [7, 8] and c in [7, 8])
            has_target = any(pos == (r, c) for pos in TARGETS.values())
            if not is_center and not has_target:
                ax.text(c + 0.5, r + 0.5, f"{r},{c}", 
                        color='#D3D3D3', fontsize=9, ha='center', va='center', zorder=2)

    plt.title("Ricochet Robots Map Layout", fontsize=16, fontweight='bold', pad=15)
    
    # 將軸標籤放在格子的正中央，而不是格線上
    plt.xticks([x + 0.5 for x in range(GRID_SIZE)], [str(x) for x in range(GRID_SIZE)])
    plt.yticks([y + 0.5 for y in range(GRID_SIZE)], [str(y) for y in range(GRID_SIZE)])
    
    # 移除 tick 的小短線，讓畫面更乾淨
    ax.tick_params(axis='both', length=0)
    
    # 將 x 軸標籤放在上方，與 y 軸原點一同顯示在左上也比較直覺
    ax.xaxis.tick_top()
    plt.grid(False)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    matrix = build_board_matrix()
    print("地圖轉換完成！正在描繪文字版地圖 (ASCII)...\n")
    draw_ascii_board(matrix)
    
    print("正在嘗試繪製精美版本地圖 (Matplotlib)...")
    draw_matplotlib_board(matrix)
