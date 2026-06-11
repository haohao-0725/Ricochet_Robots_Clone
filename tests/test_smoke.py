"""
基本 smoke test，確認核心模組可以建構與執行。

執行方式（需先設定 offscreen，避免 CI / 無顯示環境開不了視窗）：

    $env:QT_QPA_PLATFORM='offscreen'
    .\\venv\\Scripts\\python.exe -m pytest tests

若沒有 pytest，也可直接執行：

    $env:QT_QPA_PLATFORM='offscreen'
    .\\venv\\Scripts\\python.exe tests\\test_smoke.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def test_gui_construction():
    """MainWindow 應可建構並關閉，不丟例外。"""
    from PyQt6.QtWidgets import QApplication
    from main_gui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    w.close()


def test_board_generation():
    """Normal / Hard / Expert 地圖生成應回傳結果。"""
    from board_generator import BoardGenerator

    for mode in ["normal", "hard"]:
        result = BoardGenerator().generate(mode, max_attempts=3)
        assert result, f"{mode} 地圖生成失敗"

    expert = BoardGenerator().generate_expert(max_attempts=3)
    assert expert, "expert 地圖生成失敗"


def test_momentum_move():
    """Momentum (v3) 規則：主動機器人撞到牆前一格停下。"""
    from momentum_rules import resolve_momentum_move

    # 4x4 空棋盤，每格四面是否有牆以 dict 表示。
    def empty_cell():
        return {"top": False, "bottom": False, "left": False, "right": False}

    size = 4
    board = [[empty_cell() for _ in range(size)] for _ in range(size)]
    # 在最右欄外緣補上右牆，讓機器人會停在邊界。
    for r in range(size):
        board[r][size - 1]["right"] = True

    robots = {"red": (0, 0)}
    result = resolve_momentum_move(board, robots, "red", "right")
    assert result.moved
    assert result.robots["red"] == (0, size - 1)


if __name__ == "__main__":
    test_gui_construction()
    test_board_generation()
    test_momentum_move()
    print("all smoke tests passed")
