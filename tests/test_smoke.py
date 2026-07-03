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
import random
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
    """所有 catalog 模式都應回傳完整 17 回合認證結果。"""
    from board_generator import BoardGenerator
    from game_engine import GameEngine
    from mode_contracts import get_mode_contract, session_meets_contract

    generated = {}
    for mode in ["normal", "hard"]:
        random.seed(7)
        result = BoardGenerator().generate(mode, max_attempts=8)
        assert result, f"{mode} 地圖生成失敗"
        generated[mode] = result
        assert result["quality"]["validated_rounds"] == 17
        assert len(result["validated_target_order"]) == 17
        assert result["quality"]["symmetry_score"] >= 0.30
        config = BoardGenerator.CONFIGS[mode]
        assert result["quality"]["round_min_steps"] >= config["round_min_steps"]
        assert result["quality"]["round_min_moved_robots"] >= config["round_min_robots"]
        assert result["quality"]["max_wall_cluster"] <= config["max_wall_cluster"]
        for round_data in result["validation_rounds"]:
            assert round_data["steps"] >= config["round_min_steps"]
            assert round_data["moved_robot_count"] >= config["round_min_robots"]
            assert len(set(round_data["moved_robots"])) == round_data["moved_robot_count"]

        if mode == "hard":
            from ricochet_robots_board_data import build_board_matrix_from_walls
            from solver import RicochetSolver

            assert result["quality"]["validated_rounds"] == 17
            assert len(result["validated_target_order"]) == 17
            assert result["quality"]["round_step_range"] <= config["max_session_step_range"]
            assert result["quality"]["max_round_step_drop"] <= config["max_round_step_drop"]
            assert result["quality"]["generator"] == "validated_catalog_v2"

            solver = RicochetSolver(build_board_matrix_from_walls(
                result["h_walls"],
                result["v_walls"],
            ))
            robots = result["robot_positions"].copy()
            for round_data in result["validation_rounds"]:
                target_name = round_data["target"]
                exact_steps, exact_path = solver.solve(
                    robots,
                    target_name.split("_")[0],
                    result["targets"][target_name],
                    max_depth=config["round_max_depth"],
                    max_states=config["max_states"],
                )
                assert exact_steps == round_data["steps"]
                assert len({color for color, _ in exact_path}) >= 3
                robots = solver.apply_path(robots, round_data["path"])

        engine = GameEngine()
        engine.load_generated_board(result)
        for index, round_data in enumerate(result["validation_rounds"]):
            assert engine.get_current_target()[0] == round_data["target"]
            for color, direction in round_data["path"]:
                assert engine.move_robot(color, direction)
            assert engine.check_win()
            if index < len(result["validation_rounds"]) - 1:
                assert not engine.next_target(mark_completed=True)

        assert session_meets_contract(
            result["validation_rounds"],
            get_mode_contract(mode),
        )

    special_results = {
        "expert": BoardGenerator().generate_expert(max_attempts=3),
        "v3_momentum": BoardGenerator().generate("v3_momentum"),
        "super_expert": BoardGenerator().generate("super_expert"),
        "chaos": BoardGenerator().generate("chaos"),
    }
    for mode, result in special_results.items():
        assert result, f"{mode} 地圖載入失敗"
        assert len(result["validation_rounds"]) == 17
        assert session_meets_contract(
            result["validation_rounds"],
            get_mode_contract(mode),
        )

    expert_rounds = special_results["expert"]["validation_rounds"]
    assert sum(
        item["features"]["diagonal_reflections"] > 0
        for item in expert_rounds
    ) >= 8
    momentum_rounds = special_results["v3_momentum"]["validation_rounds"]
    assert sum(
        item["features"]["momentum_collisions"] > 0
        for item in momentum_rounds
    ) >= 15
    # collision finale: every momentum round's optimal ENDS with a crash
    assert all(
        item["features"].get("final_move_momentum_collisions", 0) > 0
        for item in momentum_rounds
    ), "Momentum 碰撞終結合約未滿足"

    chaos_result = special_results["chaos"]
    assert chaos_result["grid_size"] == 25
    assert len(chaos_result["portals"]) == 10
    assert len(chaos_result["sand_cells"]) == 8
    chaos_rounds = chaos_result["validation_rounds"]
    assert all(
        item["features"].get("chaos_events", 0) > 0
        for item in chaos_rounds
    ), "Chaos 每題都必須觸發至少一次特殊機制"

    # chaos rounds must replay through the engine (rules parity with the GUI)
    from game_engine import GameEngine
    engine = GameEngine()
    engine.load_generated_board(chaos_result)
    for index, round_data in enumerate(chaos_rounds):
        assert engine.get_current_target()[0] == round_data["target"]
        for color, direction in round_data["path"]:
            assert engine.move_robot(color, direction)
        assert engine.check_win()
        if index < len(chaos_rounds) - 1:
            assert not engine.next_target(mark_completed=True)


def test_easy_remains_static():
    """Easy 必須維持固定原圖，不進入動態地圖生成流程。"""
    from game_engine import GameEngine
    from ricochet_robots_board_data import TARGETS, build_board_matrix

    engine = GameEngine()
    assert engine.difficulty_mode == "easy"
    assert not engine.validated_target_order
    assert dict(engine.targets) == dict(TARGETS)
    assert engine.board == build_board_matrix()


def test_solver_optimal_path_and_replay():
    """A* 應保留最短解，且 canonical helper path 可正確還原顏色。"""
    from ricochet_robots_board_data import TARGETS, build_board_matrix
    from solver import RicochetSolver

    robots = {
        "Blue": (7, 6),
        "Yellow": (6, 8),
        "Green": (8, 9),
        "Red": (9, 7),
    }
    solver = RicochetSolver(build_board_matrix())
    steps, path = solver.solve(robots, "Yellow", TARGETS["Yellow_Star"])

    assert steps == 10
    assert len(path) == steps
    assert solver.last_stats["algorithm"] == "astar-canonical"
    assert solver.last_stats["states_expanded"] < 100000
    end_robots = solver.apply_path(robots, path)
    assert end_robots["Yellow"] == TARGETS["Yellow_Star"]


def test_generated_round_chain_and_test_mode():
    """Normal 生成證明應可連續回放完整 17 回合。"""
    from board_generator import BoardGenerator
    from game_engine import GameEngine
    from ricochet_robots_board_data import build_board_matrix_from_walls
    from solver import RicochetSolver

    random.seed(11)
    result = BoardGenerator().generate("normal", max_attempts=3)
    assert result

    board = build_board_matrix_from_walls(result["h_walls"], result["v_walls"])
    solver = RicochetSolver(board)
    robots = result["robot_positions"].copy()
    for round_data in result["validation_rounds"]:
        target_name = round_data["target"]
        robots = solver.apply_path(robots, round_data["path"])
        target_color = target_name.split("_")[0]
        target_pos = result["targets"][target_name]
        if target_color == "Wild":
            assert target_pos in robots.values()
        else:
            assert robots[target_color] == target_pos

    engine = GameEngine()
    engine.load_generated_board(result)
    assert engine.get_current_target()[0] == result["validated_target_order"][0]
    engine.toggle_test_mode(True)
    assert engine.test_mode
    assert engine.revert_test_mode()
    engine.toggle_test_mode(False)

    for index, round_data in enumerate(result["validation_rounds"]):
        assert engine.get_current_target()[0] == round_data["target"]
        for color, direction in round_data["path"]:
            assert engine.move_robot(color, direction)
        assert engine.check_win()
        if index < len(result["validation_rounds"]) - 1:
            assert not engine.next_target(mark_completed=True)


def test_catalog_topology_families():
    """Hard catalog 應包含 12 張基底及四個拓樸家族。"""
    from collections import Counter

    from map_catalog import load_catalog

    catalog = load_catalog()
    hard_maps = [
        item for item in catalog["maps"]
        if item["mode"] == "hard" and item["certified"]
    ]
    assert len(hard_maps) == 12
    family_counts = Counter(item["family"] for item in hard_maps)
    assert set(family_counts) == {
        "balanced_rooms",
        "offset_pinwheel",
        "axial_gates",
        "central_locks",
    }
    assert all(count == 3 for count in family_counts.values())


def test_release_catalog_invariants():
    """發布前的 catalog 不變量：Super Expert 與 Hard 不同、Momentum 尾段不驟降。"""
    from map_catalog import load_catalog

    catalog = load_catalog()
    by_mode = {}
    for item in catalog["maps"]:
        if item.get("certified"):
            by_mode.setdefault(item["mode"], []).append(item)

    hard_topologies = {
        item["features"]["topology_signature"] for item in by_mode.get("hard", [])
    }
    hard_trajectories = {
        item["features"]["trajectory_signature"] for item in by_mode.get("hard", [])
    }

    super_expert = by_mode.get("super_expert", [])
    assert super_expert, "缺少 Super Expert 認證地圖"
    for item in super_expert:
        # Super Expert 不可再是某張 Hard 的改名複本。
        assert item["features"]["topology_signature"] not in hard_topologies
        assert item["features"]["trajectory_signature"] not in hard_trajectories

    momentum = by_mode.get("v3_momentum", [])
    assert momentum, "缺少 Momentum 認證地圖"
    for item in momentum:
        steps = [round_data["steps"] for round_data in item["rounds"]]
        # 尾段不可再驟降到 2-3 步。
        assert min(steps) >= 4, f"Momentum 最小步數 {min(steps)} < 4"
        drops = [a - b for a, b in zip(steps, steps[1:])]
        assert max(drops, default=0) <= 3
        collision_rounds = sum(
            round_data["features"].get("momentum_collisions", 0) > 0
            for round_data in item["rounds"]
        )
        assert collision_rounds >= 15, f"只有 {collision_rounds} 題含推撞"


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
    test_easy_remains_static()
    test_board_generation()
    test_solver_optimal_path_and_replay()
    test_generated_round_chain_and_test_mode()
    test_catalog_topology_families()
    test_release_catalog_invariants()
    test_momentum_move()
    print("all smoke tests passed")
