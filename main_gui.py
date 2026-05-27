import sys
import os
import glob
import shutil
from collections import deque
import math
import random
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QGraphicsView, 
                             QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsEllipseItem,
                             QGridLayout, QScrollArea, QGraphicsOpacityEffect, QMessageBox,
                             QMenu, QInputDialog)
from PyQt6.QtGui import QPixmap, QColor, QPainter, QPen, QImage, QPainterPath, QIcon, QKeySequence, QShortcut
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QPointF, QEasingCurve, pyqtProperty, QObject, QThread, pyqtSignal, QSize, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QSoundEffect

from game_engine import GameEngine
from ricochet_robots_board_data import TARGETS, GRID_SIZE, COLORED_HWALLS, COLORED_VWALLS
from solver import RicochetSolver

class BoardGeneratorThread(QThread):
    board_ready = pyqtSignal(dict)
    progress_signal = pyqtSignal(str)

    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def run(self):
        try:
            from board_generator import BoardGenerator
            gen = BoardGenerator()
            if self.mode == 'expert':
                board_data = gen.generate_expert(
                    progress_callback=self.progress_signal.emit,
                    cancel_callback=self.is_cancelled,
                )
            else:
                board_data = gen.generate(
                    self.mode,
                    progress_callback=self.progress_signal.emit,
                    cancel_callback=self.is_cancelled,
                )
            if self._cancelled:
                self.board_ready.emit({'__cancelled__': True})
                return
            self.board_ready.emit(board_data or {})
        except Exception as e:
            print("Generator error:", e)
            import traceback; traceback.print_exc()
            self.board_ready.emit({})

class SolverThread(QThread):
    finished_signal = pyqtSignal(int, int, list)
    progress_signal = pyqtSignal(int, int)

    def __init__(
        self,
        task_id,
        board,
        robots_dict,
        target_color,
        target_pos,
        grid_size=16,
        diagonal_walls=None,
        movement_mode='classic',
    ):
        super().__init__()
        self.task_id = task_id
        self.board = board
        self.robots_dict = robots_dict
        self.target_color = target_color
        self.target_pos = target_pos
        self.grid_size = grid_size
        self.diagonal_walls = diagonal_walls or {}
        self.movement_mode = movement_mode
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def run(self):
        diag = {tuple(k) if isinstance(k, list) else k: v for k, v in self.diagonal_walls.items()} if self.diagonal_walls else {}
        solver = RicochetSolver(
            self.board,
            grid_size=self.grid_size,
            diagonal_walls=diag,
            movement_mode=self.movement_mode,
        )
        steps, path = solver.solve(
            self.robots_dict,
            self.target_color,
            self.target_pos,
            cancel_callback=self.is_cancelled,
            progress_callback=lambda expanded, depth: self.progress_signal.emit(expanded, depth),
        )
        self.finished_signal.emit(self.task_id, steps, path)


class TargetPickerThread(QThread):
    finished_signal = pyqtSignal(int, int)

    def __init__(
        self,
        task_id,
        board,
        robots_dict,
        targets,
        completed_targets,
        current_target_idx,
        grid_size=16,
        diagonal_walls=None,
        movement_mode='classic',
        exclude_current=False,
    ):
        super().__init__()
        self.task_id = task_id
        self.board = board
        self.robots_dict = robots_dict.copy()
        self.targets = [(name, tuple(pos)) for name, pos in targets]
        self.completed_targets = set(completed_targets)
        self.current_target_idx = current_target_idx
        self.grid_size = grid_size
        self.diagonal_walls = diagonal_walls or {}
        self.movement_mode = movement_mode
        self.exclude_current = exclude_current
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def run(self):
        next_idx = self.pick_target_idx()
        self.finished_signal.emit(self.task_id, next_idx)

    def ordered_uncompleted_target_indices(self):
        candidates = []
        offsets = range(1, len(self.targets)) if self.exclude_current else range(len(self.targets))
        for offset in offsets:
            idx = (self.current_target_idx + offset) % len(self.targets)
            name, _ = self.targets[idx]
            if name not in self.completed_targets:
                candidates.append(idx)
        if self.exclude_current and not candidates and self.targets:
            current_name, _ = self.targets[self.current_target_idx]
            if current_name not in self.completed_targets:
                candidates.append(self.current_target_idx)
        return candidates

    def target_solve_steps(self, target_name, target_pos, max_depth=22, max_states=220000):
        if self.is_cancelled():
            return -2
        try:
            target_color = target_name.split('_')[0]
            diag = {tuple(k) if isinstance(k, list) else k: v for k, v in self.diagonal_walls.items()} if self.diagonal_walls else {}
            solver = RicochetSolver(
                self.board,
                grid_size=self.grid_size,
                diagonal_walls=diag,
                movement_mode=self.movement_mode,
            )
            steps, _ = solver.solve(
                self.robots_dict,
                target_color,
                target_pos,
                max_depth=max_depth,
                max_states=max_states,
                cancel_callback=self.is_cancelled,
            )
            return steps
        except Exception:
            return -1

    def pick_target_idx(self):
        candidates = self.ordered_uncompleted_target_indices()
        if not candidates:
            return self.current_target_idx

        needs_full_solve = []
        within_three_steps = []
        unknown = []

        for idx in candidates:
            name, pos = self.targets[idx]
            steps = self.target_solve_steps(name, pos, max_depth=3, max_states=50000)
            if 0 <= steps <= 3:
                within_three_steps.append(idx)
            else:
                needs_full_solve.append(idx)

        for idx in needs_full_solve:
            if self.is_cancelled():
                return candidates[0]
            name, pos = self.targets[idx]
            steps = self.target_solve_steps(name, pos)
            if steps > 3:
                return idx
            if 0 <= steps <= 3:
                within_three_steps.append(idx)
            else:
                unknown.append(idx)

        for group in (within_three_steps, unknown):
            if group:
                return group[0]

        return self.current_target_idx

CELL_SIZE = 40
BOARD_SIZE = CELL_SIZE * GRID_SIZE
DIAG_COLOR_MAP = {
    'Red':    '#FF4444',
    'Blue':   '#4488FF',
    'Green':  '#44EE44',
    'Yellow': '#FFEE22',
}
ROBOT_KEY_MAP = {
    Qt.Key.Key_1: 'Red',
    Qt.Key.Key_2: 'Blue',
    Qt.Key.Key_3: 'Green',
    Qt.Key.Key_4: 'Yellow',
    Qt.Key.Key_5: 'Silver',
}
DIRECTION_KEY_MAP = {
    Qt.Key.Key_Up: 'top',
    Qt.Key.Key_Down: 'bottom',
    Qt.Key.Key_Left: 'left',
    Qt.Key.Key_Right: 'right',
}

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

# 蝘駁??????脣??(remove_bg, draw_vector_icon, create_token_pixmap)

class ClickableLabel(QLabel):
    clicked = pyqtSignal()
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

class AnimatablePixmap(QObject):
    def __init__(self, item):
        super().__init__()
        self.item = item

    @pyqtProperty(QPointF)
    def pos(self):
        return self.item.pos()

    @pos.setter
    def pos(self, p):
        self.item.setPos(p)

class BoardView(QGraphicsView):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setMinimumSize(400, 400)
        self.scene.setSceneRect(0, 0, BOARD_SIZE, BOARD_SIZE)
        
        self.setBackgroundBrush(QColor("#1A1A1A"))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.robot_items = {}
        self.animating = False
        self.selected_color = None
        self.animations = []

        self.arrow_items = {}
        from PyQt6.QtWidgets import QGraphicsPolygonItem
        for d in ['top', 'bottom', 'left', 'right']:
            poly = QGraphicsPolygonItem()
            self.arrow_items[d] = poly
            poly.setZValue(11)
            poly.hide()
            self.scene.addItem(poly)

        self.target_highlight_item = QGraphicsRectItem(0, 0, CELL_SIZE, CELL_SIZE)
        self.target_highlight_item.setPen(QPen(QColor(255, 255, 180, 95), 1))
        self.target_highlight_item.setBrush(QColor(255, 224, 64, 135))
        self.target_highlight_item.setZValue(-1)
        self.scene.addItem(self.target_highlight_item)

        self.highlight_item = QGraphicsEllipseItem(3, 3, CELL_SIZE - 6, CELL_SIZE - 6)
        self.highlight_item.setPen(QPen(QColor(255, 255, 255, 220), 3))
        self.highlight_item.setBrush(QColor(255, 255, 255, 60))
        self.highlight_item.setZValue(9)
        self.highlight_item.hide()
        self.scene.addItem(self.highlight_item)

        self.assets = {}
        self.load_assets()

        self.draw_board()
        self.draw_targets()
        self.draw_robots()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refit_to_board()

    def refit_to_board(self):
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def update_arrows(self):
        if not self.selected_color or self.animating:
            for p in self.arrow_items.values(): p.hide()
            return
            
        r, c = self.engine.robots[self.selected_color]
        color = self.get_color_obj(self.selected_color)
        color.setAlpha(180)
        brush = QColor(color)
        
        w = CELL_SIZE
        h = CELL_SIZE
        
        from PyQt6.QtGui import QPolygonF
        for d, item in self.arrow_items.items():
            item.setBrush(brush)
            item.setPen(QPen(Qt.PenStyle.NoPen))
            
            pts = []
            pos = None
            if d == 'top' and r > 0:
                pts = [QPointF(0, -8), QPointF(-8, 8), QPointF(8, 8)]
                pos = QPointF(c * w + w/2, (r-1) * h + h/2)
            elif d == 'bottom' and r < self.engine.grid_size - 1:
                pts = [QPointF(0, 8), QPointF(-8, -8), QPointF(8, -8)]
                pos = QPointF(c * w + w/2, (r+1) * h + h/2)
            elif d == 'left' and c > 0:
                pts = [QPointF(-8, 0), QPointF(8, -8), QPointF(8, 8)]
                pos = QPointF((c-1) * w + w/2, r * h + h/2)
            elif d == 'right' and c < self.engine.grid_size - 1:
                pts = [QPointF(8, 0), QPointF(-8, -8), QPointF(-8, 8)]
                pos = QPointF((c+1) * w + w/2, r * h + h/2)
                
            if pos:
                item.setPolygon(QPolygonF(pts))
                item.setPos(pos)
                item.show()
            else:
                item.hide()

    def load_assets(self):
        base_dir = resource_path('assets')
        self.raw_pixmaps = {}
        
        for color in ['red', 'blue', 'green', 'yellow']:
            for shape in ['planet', 'star', 'moon', 'gear']:
                name = f"{color.capitalize()}_{shape.capitalize()}"
                path = os.path.join(base_dir, f"{color}_{shape}.png")
                if os.path.exists(path):
                    self.raw_pixmaps[name] = QPixmap(path)
                    
            path = os.path.join(base_dir, f"{color}_robot.png")
            if os.path.exists(path):
                self.raw_pixmaps[color.capitalize()] = QPixmap(path)
                
        path = os.path.join(base_dir, "black_hole.png")
        if os.path.exists(path):
            self.raw_pixmaps["Wild_Vortex"] = QPixmap(path)
            
        path = os.path.join(base_dir, "fifth_robot.png")
        if os.path.exists(path):
            self.raw_pixmaps["Silver"] = QPixmap(path)

    def get_token_pixmap(self, name, size=None):
        pm = self.raw_pixmaps.get(name)
        if pm and not pm.isNull():
            if size is not None:
                return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            return pm
        if size is None: size = CELL_SIZE
        pm = QPixmap(size, size)
        pm.fill(QColor("transparent"))
        return pm

    def get_color_obj(self, color_name):
        cmap = {'Red': QColor(255, 60, 60), 'Blue': QColor(60, 150, 255), 
                'Green': QColor(80, 255, 80), 'Yellow': QColor(255, 230, 50),
                'Wild': QColor(200, 100, 255)}
        return cmap.get(color_name, QColor(255,255,255))

    def draw_board(self):
        gs = self.engine.grid_size
        cs = CELL_SIZE  # cell size stays 40 for 16x16; will be smaller for 32x32
        board_px = cs * gs
        self.scene.setSceneRect(0, 0, board_px, board_px)

        pen = QPen(QColor("#333333"), 1)
        for i in range(gs + 1):
            self.scene.addLine(i * cs, 0, i * cs, board_px, pen)
            self.scene.addLine(0, i * cs, board_px, i * cs, pen)

        cx = gs // 2 - 1
        center = QGraphicsRectItem(cx * cs, cx * cs, 2 * cs, 2 * cs)
        center.setBrush(QColor("#0a0a0a"))
        self.scene.addItem(center)

        for r in range(gs):
            for c in range(gs):
                cell = self.engine.board[r][c]
                x, y = c * cs, r * cs
                
                if cell['top']:
                    color = COLORED_HWALLS.get((r-1, c))
                    wp = QPen(QColor(color) if color else QColor("#DDDDDD"), 5)
                    self.scene.addLine(x, y, x + cs, y, wp)
                if cell['bottom']:
                    color = COLORED_HWALLS.get((r, c))
                    wp = QPen(QColor(color) if color else QColor("#DDDDDD"), 5)
                    self.scene.addLine(x, y + cs, x + cs, y + cs, wp)
                if cell['left']:
                    color = COLORED_VWALLS.get((r, c-1))
                    wp = QPen(QColor(color) if color else QColor("#DDDDDD"), 5)
                    self.scene.addLine(x, y, x, y + cs, wp)
                if cell['right']:
                    color = COLORED_VWALLS.get((r, c))
                    wp = QPen(QColor(color) if color else QColor("#DDDDDD"), 5)
                    self.scene.addLine(x + cs, y, x + cs, y + cs, wp)

        diag_walls = self.engine.diagonal_walls
        if diag_walls:
            for key, d_wall in diag_walls.items():
                if isinstance(key, (list, tuple)):
                    dr, dc = int(key[0]), int(key[1])
                else:
                    dr, dc = key
                x, y = dc * cs, dr * cs
                color_str = DIAG_COLOR_MAP.get(d_wall.get('color', 'Red'), '#FF4444')
                diag_pen = QPen(QColor(color_str), 4)
                diag_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                if d_wall['type'] == '/':
                    self.scene.addLine(x + 4, y + cs - 4, x + cs - 4, y + 4, diag_pen)
                else:
                    self.scene.addLine(x + 4, y + 4, x + cs - 4, y + cs - 4, diag_pen)

    def draw_targets(self):
        cs = CELL_SIZE
        for name, (r, c) in self.engine.targets:
            pm = self.get_token_pixmap(name, size=None)
            item = QGraphicsPixmapItem(pm)
            if pm.width() > 0:
                item.setScale(cs / pm.width())
            item.setPos(c * cs, r * cs)
            item.setZValue(1)
            self.scene.addItem(item)
        self.update_current_target_highlight()

    def update_current_target_highlight(self):
        if not hasattr(self, 'target_highlight_item'):
            return
        _, (r, c) = self.engine.get_current_target()
        self.target_highlight_item.setRect(0, 0, CELL_SIZE, CELL_SIZE)
        self.target_highlight_item.setPos(c * CELL_SIZE, r * CELL_SIZE)
        self.target_highlight_item.show()

    def full_redraw(self):
        self.scene.clear()
        self.robot_items.clear()

        from PyQt6.QtWidgets import QGraphicsPolygonItem
        for d in ['top', 'bottom', 'left', 'right']:
            poly = QGraphicsPolygonItem()
            self.arrow_items[d] = poly
            poly.setZValue(11)
            poly.hide()
            self.scene.addItem(poly)

        self.target_highlight_item = QGraphicsRectItem(0, 0, CELL_SIZE, CELL_SIZE)
        self.target_highlight_item.setPen(QPen(QColor(255, 255, 180, 95), 1))
        self.target_highlight_item.setBrush(QColor(255, 224, 64, 135))
        self.target_highlight_item.setZValue(-1)
        self.scene.addItem(self.target_highlight_item)

        self.highlight_item = QGraphicsEllipseItem(3, 3, CELL_SIZE - 6, CELL_SIZE - 6)
        self.highlight_item.setPen(QPen(QColor(255, 255, 255, 220), 3))
        self.highlight_item.setBrush(QColor(255, 255, 255, 60))
        self.highlight_item.setZValue(9)
        self.highlight_item.hide()
        self.scene.addItem(self.highlight_item)

        self.draw_board()
        self.draw_targets()
        self.draw_robots()
        QTimer.singleShot(0, self.refit_to_board)

    def draw_robots(self):
        cs = CELL_SIZE
        for pm in self.robot_items.values():
            if pm.scene() == self.scene:
                self.scene.removeItem(pm)
        self.robot_items.clear()
        
        for color, (r, c) in self.engine.robots.items():
            pm = self.get_token_pixmap(color, size=None)
            item = QGraphicsPixmapItem(pm)
            if pm.width() > 0:
                item.setScale(cs / pm.width())
            item.setPos(c * cs, r * cs)
            item.setZValue(10)
            self.scene.addItem(item)
            self.robot_items[color] = item

    def select_robot(self, color):
        if self.animating or color not in self.engine.robots:
            return False
        rr, rc = self.engine.robots[color]
        self.selected_color = color
        self.highlight_item.setPos(rc * CELL_SIZE, rr * CELL_SIZE)
        self.highlight_item.show()
        self.update_arrows()
        self.setFocus()
        return True

    def move_selected(self, direction):
        if self.animating or not self.selected_color:
            return False
        if self.engine.move_robot(self.selected_color, direction):
            steps = getattr(self.engine, 'last_move_animation_steps', None)
            if steps:
                self.animate_move_sequence(steps)
            else:
                changed = getattr(self.engine, 'last_move_changed_colors', [self.selected_color]) or [self.selected_color]
                self.animate_robots(changed)
            return True
        return False

    def keyPressEvent(self, event):
        key = event.key()
        if key in ROBOT_KEY_MAP:
            if self.select_robot(ROBOT_KEY_MAP[key]):
                return

        direction = DIRECTION_KEY_MAP.get(key)
        if direction and self.move_selected(direction):
            return

        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self.animating: return
        pos = self.mapToScene(event.pos())
        c = int(pos.x() // CELL_SIZE)
        r = int(pos.y() // CELL_SIZE)

        for color, (rr, rc) in self.engine.robots.items():
            if rr == r and rc == c:
                self.select_robot(color)
                return

        if self.selected_color:
            rr, rc = self.engine.robots[self.selected_color]
            direction = None
            if r == rr and c > rc: direction = 'right'
            elif r == rr and c < rc: direction = 'left'
            elif c == rc and r > rr: direction = 'bottom'
            elif c == rc and r < rr: direction = 'top'

            if direction:
                self.move_selected(direction)

    def animate_robot(self, color):
        self.animate_robots([color])

    def animate_move_sequence(self, steps):
        self.animation_sequence = list(steps)
        self.animating = True
        self.highlight_item.hide()
        self.update_arrows()
        if hasattr(self.window(), 'play_sound'):
            self.window().play_sound('move')
        if hasattr(self.window(), 'update_ui'):
            self.window().update_ui()
        self.play_next_animation_step()

    def play_next_animation_step(self):
        if not getattr(self, 'animation_sequence', None):
            self.on_animation_finished()
            return

        step = self.animation_sequence.pop(0)
        color = step.get('color')
        to_pos = tuple(step.get('to', ()))
        if color not in self.robot_items or len(to_pos) != 2:
            self.play_next_animation_step()
            return

        r, c = to_pos
        item = self.robot_items[color]
        end_pos = QPointF(c * CELL_SIZE, r * CELL_SIZE)
        if item.pos() == end_pos:
            self.play_next_animation_step()
            return

        anim_obj = AnimatablePixmap(item)
        self.animations.append(anim_obj)

        anim = QPropertyAnimation(anim_obj, b"pos")
        anim.setDuration(150)
        anim.setStartValue(item.pos())
        anim.setEndValue(end_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        anim.finished.connect(self.on_sequence_step_finished)
        anim.start()

        anim_obj.anim = anim

    def on_sequence_step_finished(self):
        self.animations.clear()
        QTimer.singleShot(40, self.play_next_animation_step)

    def animate_robots(self, colors):
        if hasattr(self.window(), 'play_sound'):
            self.window().play_sound('move')
        self.animating = True
        self.pending_animation_count = 0

        for color in colors:
            if color not in self.robot_items or color not in self.engine.robots:
                continue
            r, c = self.engine.robots[color]
            end_pos = QPointF(c * CELL_SIZE, r * CELL_SIZE)
            item = self.robot_items[color]

            if item.pos() == end_pos:
                continue

            anim_obj = AnimatablePixmap(item)
            self.animations.append(anim_obj)

            anim = QPropertyAnimation(anim_obj, b"pos")
            anim.setDuration(150)
            anim.setStartValue(item.pos())
            anim.setEndValue(end_pos)
            anim.setEasingCurve(QEasingCurve.Type.OutQuad)
            anim.finished.connect(self.on_animation_finished)
            anim.start()

            anim_obj.anim = anim
            self.pending_animation_count += 1

        if self.pending_animation_count == 0:
            self.draw_robots()
            self.on_animation_finished()
            return
        
        self.highlight_item.hide()
        self.update_arrows()
        
        if hasattr(self.window(), 'update_ui'):
            self.window().update_ui()

    def on_animation_finished(self):
        if getattr(self, 'animation_sequence', None):
            self.animation_sequence = []
        if getattr(self, 'pending_animation_count', 0) > 1:
            self.pending_animation_count -= 1
            return
        self.pending_animation_count = 0
        self.animating = False
        self.animations.clear()
        self.draw_robots()
        
        if self.selected_color:
            r, c = self.engine.robots[self.selected_color]
            self.highlight_item.setPos(c * CELL_SIZE, r * CELL_SIZE)
            self.highlight_item.show()
            self.update_arrows()
            
        if hasattr(self.window(), 'check_win'):
            self.window().check_win()
        if hasattr(self.window(), 'update_ui'):
            self.window().update_ui()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.engine = GameEngine()
        self.solver_task_id = 0
        self._migrate_legacy_save_if_needed()
        self.audio_settings = self.engine.read_settings(self.get_save_path())
        self.music_enabled = bool(self.audio_settings.get('music_enabled', True))
        self.sound_enabled = bool(self.audio_settings.get('sound_enabled', True))
        self.bgm_files = self.find_bgm_files()
        self.bgm_index = 0
        self.bgm_player = None
        self.bgm_audio_output = None
        self.sound_effects = {}
        self.solution_path_visible = False
        
        self.timer_seconds = 90
        self.timer_running = False
        self.flash_count = 0
        self.qtimer = QTimer(self)
        self.qtimer.timeout.connect(self.timer_tick)
        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self.flash_tick)
        self.solver_dots = 0
        self.solver_timer = QTimer(self)
        self.solver_timer.timeout.connect(self.update_solver_progress_text)
        self.active_solver_thread = None
        self.target_picker_task_id = 0
        self.active_target_picker_thread = None
        self.pending_momentum_target_pick = None
        self.waiting_for_momentum_target_pick = False
        self.pending_generation_previous_state = None
        self.pending_generation_mode = None
        
        self.init_ui()
        self.init_keyboard_shortcuts()
        self.init_audio()
        self.update_audio_button_states()
        if self.music_enabled:
            QTimer.singleShot(0, self.start_bgm)

    def set_default_style(self):
        self.setStyleSheet("QMainWindow { background-color: #0F0F13; color: #FFFFFF; font-family: 'Segoe UI', Arial; }")

    def set_test_mode_style(self):
        self.setStyleSheet("QMainWindow { background-color: #4A1515; color: #FFFFFF; font-family: 'Segoe UI', Arial; }")

    def init_keyboard_shortcuts(self):
        self.keyboard_shortcuts = []
        for key, color in ROBOT_KEY_MAP.items():
            shortcut = QShortcut(QKeySequence(key.value), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(lambda color=color: self.board_view.select_robot(color))
            self.keyboard_shortcuts.append(shortcut)

        for key, direction in DIRECTION_KEY_MAP.items():
            shortcut = QShortcut(QKeySequence(key.value), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(lambda direction=direction: self.board_view.move_selected(direction))
            self.keyboard_shortcuts.append(shortcut)

    def init_ui(self):
        self.setWindowTitle("Ricochet Robots - Python")
        self.set_default_style()

        main_widget = QWidget()
        layout = QHBoxLayout()

        self.board_view = BoardView(self.engine, self)
        layout.addWidget(self.board_view)

        # ====== Center Panel (Controls) ======
        panel = QWidget()
        panel.setFixedWidth(250)
        panel_layout = QVBoxLayout()
        panel.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 30, 40, 200);
                border-radius: 15px;
            }
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #EEEEEE;
                background: transparent;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 20);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                color: white;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 40);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 60);
            }
            QPushButton:checked {
                background-color: rgba(255, 150, 150, 100);
                border: 2px solid rgba(255, 150, 150, 200);
            }
        """)

        # Timer UI
        timer_widget = QWidget()
        timer_widget.setStyleSheet("background-color: rgba(0, 0, 0, 100); border-radius: 10px; padding: 5px;")
        t_layout = QVBoxLayout()
        self.time_display = QLabel("01:30")
        self.time_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_display.setStyleSheet("font-size: 32px; color: #FFD700;")
        
        self.win_count_clicks = 0
        self.win_count_lbl = ClickableLabel("破關次數: 0")
        self.win_count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.win_count_lbl.setStyleSheet("font-size: 16px; color: #55ff55; font-weight: bold;")
        self.win_count_lbl.clicked.connect(self.on_win_count_clicked)
        
        btn_layout = QHBoxLayout()
        self.t_start_btn = QPushButton("開始 / 暫停")
        self.t_start_btn.clicked.connect(self.toggle_timer)
        self.t_reset_btn = QPushButton("重置計時")
        self.t_reset_btn.clicked.connect(self.reset_timer)
        btn_layout.addWidget(self.t_start_btn)
        btn_layout.addWidget(self.t_reset_btn)
        
        t_layout.addWidget(self.win_count_lbl)
        t_layout.addWidget(self.time_display)
        t_layout.addLayout(btn_layout)
        timer_widget.setLayout(t_layout)

        # Target UI
        self.target_label = QLabel("目前目標")
        self.target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.target_image = QLabel()
        self.target_image.setFixedSize(120, 120)
        self.target_image.setStyleSheet("background: rgba(0,0,0,100); border: 2px solid rgba(255,255,255,30); border-radius: 10px;")
        self.target_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_layout = QHBoxLayout()
        image_layout.addWidget(self.target_image)

        self.steps_label = QLabel("已嘗試: 0")
        self.steps_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.steps_label.setStyleSheet("font-size: 24px; color: #55aaff;")

        # Solver Panel
        solver_layout = QVBoxLayout()
        self.eye_btn = QPushButton("顯示提示面板")
        self.eye_btn.setCheckable(True)
        self.eye_btn.setChecked(False)
        self.eye_btn.clicked.connect(self.toggle_solver_panel)
        
        self.solver_panel = QWidget()
        sp_layout = QVBoxLayout(self.solver_panel)
        
        self.calc_btn = QPushButton("⚙️ 開始計算最佳解")
        self.calc_btn.setStyleSheet("background-color: rgba(100, 100, 200, 150); font-weight: bold;")
        self.calc_btn.clicked.connect(self.trigger_solver)
        
        self.solver_steps_lbl = QLabel("")
        self.solver_steps_lbl.setStyleSheet("color: #FFD700; font-weight: bold; font-size: 16px;")
        self.solver_steps_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.show_path_btn = QPushButton("顯示解答路徑（先按計算）")
        self.show_path_btn.clicked.connect(self.toggle_solution_path)
        self.show_path_btn.setEnabled(False)
        self.solver_path_lbl = QLabel("")
        self.solver_path_lbl.setWordWrap(True)
        self.solver_path_lbl.setMinimumHeight(60)
        self.solver_path_lbl.hide()
        
        sp_layout.addWidget(self.calc_btn)
        sp_layout.addWidget(self.solver_steps_lbl)
        sp_layout.addWidget(self.show_path_btn)
        sp_layout.addWidget(self.solver_path_lbl)
        self.solver_panel.hide()
        
        solver_layout.addWidget(self.eye_btn)
        solver_layout.addWidget(self.solver_panel)

        # Test Mode UI
        self.test_mode_btn = QPushButton("試走模式")
        self.test_mode_btn.setCheckable(True)
        self.test_mode_btn.clicked.connect(self.toggle_test_mode)
        
        self.full_revert_btn = QPushButton("還原試走")
        self.full_revert_btn.setStyleSheet("background-color: rgba(255, 100, 100, 80); border: 2px solid rgba(255,50,50,200);")
        self.full_revert_btn.clicked.connect(self.revert_test_mode)
        self.full_revert_btn.hide()

        # Save / Load controls
        save_load_layout = QHBoxLayout()
        self.save_btn = QPushButton("存檔")
        self.save_btn.clicked.connect(self.save_game)
        self.load_btn = QPushButton("讀取")
        self.load_btn.clicked.connect(self.load_game)
        save_load_layout.addWidget(self.save_btn)
        save_load_layout.addWidget(self.load_btn)

        # Regular controls
        self.undo_btn = QPushButton("復原上一步")
        self.undo_btn.clicked.connect(self.undo_move)

        self.next_btn = QPushButton("下一個目標")
        self.next_btn.clicked.connect(self.next_target)

        # Assemble Center Panel
        panel_layout.addWidget(timer_widget)
        panel_layout.addSpacing(15)
        panel_layout.addWidget(self.target_label)
        panel_layout.addLayout(image_layout)
        panel_layout.addSpacing(10)
        panel_layout.addWidget(self.steps_label)
        panel_layout.addLayout(solver_layout)
        panel_layout.addSpacing(20)
        panel_layout.addWidget(self.test_mode_btn)
        panel_layout.addWidget(self.full_revert_btn)
        panel_layout.addSpacing(10)
        panel_layout.addLayout(save_load_layout)
        panel_layout.addWidget(self.undo_btn)
        panel_layout.addStretch()
        panel_layout.addWidget(self.next_btn)
        
        panel.setLayout(panel_layout)
        layout.addWidget(panel)

        # ====== Right Panel (Checklist) ======
        checklist_panel = QWidget()
        checklist_panel.setFixedWidth(140)
        checklist_layout = QVBoxLayout()
        checklist_layout.setContentsMargins(0,0,0,0)

        cl_title = QLabel("已完成目標")
        cl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl_title.setStyleSheet("font-weight: bold; font-size: 16px;")
        checklist_layout.addWidget(cl_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        scroll_content = QWidget()
        self.cl_grid = QGridLayout()
        self.cl_grid.setSpacing(5)

        fixed_order = [
            'Red_Moon', 'Blue_Moon',
            'Red_Planet', 'Blue_Planet',
            'Red_Star', 'Blue_Star',
            'Red_Gear', 'Blue_Gear',
            'Green_Moon', 'Yellow_Moon',
            'Green_Planet', 'Yellow_Planet',
            'Green_Star', 'Yellow_Star',
            'Green_Gear', 'Yellow_Gear',
            'Wild_Vortex'
        ]

        self.cl_icons = {}
        for idx, name in enumerate(fixed_order):
            if name not in TARGETS: continue
            lbl = QLabel()
            lbl.setFixedSize(45, 45)
            pm = self.board_view.get_token_pixmap(name, 45)
            lbl.setPixmap(pm)
            effect = QGraphicsOpacityEffect()
            effect.setOpacity(0.3)
            lbl.setGraphicsEffect(effect)
            self.cl_icons[name] = lbl
            r = idx // 2
            c = idx % 2
            self.cl_grid.addWidget(lbl, r, c, Qt.AlignmentFlag.AlignCenter)

        scroll_content.setLayout(self.cl_grid)
        scroll.setWidget(scroll_content)
        checklist_layout.addWidget(scroll)

        self.reset_btn = QPushButton("重置遊戲")
        self.reset_btn.setStyleSheet("background-color: rgba(255, 50, 50, 80); border: 1px solid rgba(255,100,100,150); border-radius: 8px; padding: 12px; font-weight:bold; color: white;")
        self.reset_btn.clicked.connect(self.reset_game)
        checklist_layout.addWidget(self.reset_btn)

        checklist_panel.setLayout(checklist_layout)
        layout.addWidget(checklist_panel)

        root_layout = QVBoxLayout()
        top_bar_layout = QHBoxLayout()

        self.info_btn = QPushButton()
        self.info_btn.setFixedSize(34, 34)
        self.info_btn.setToolTip("模式說明")
        self.info_btn.setIcon(QIcon(resource_path("assets/information.png")))
        self.info_btn.setIconSize(QSize(22, 22))
        self.info_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 17px;
                padding: 0;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 28);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 46);
            }
        """)
        self.info_btn.clicked.connect(self.show_mode_info)
        
        self.btn_easy = QPushButton("Easy")
        self.btn_easy.clicked.connect(lambda: self.switch_difficulty('easy'))
        
        self.btn_normal = QPushButton("Normal")
        self.btn_normal.clicked.connect(lambda: self.switch_difficulty('normal'))
        
        self.btn_hard = QPushButton("Hard")
        self.btn_hard.clicked.connect(lambda: self.switch_difficulty('hard'))
        
        self.btn_expert = QPushButton("Expert")
        self.btn_expert.clicked.connect(lambda: self.switch_difficulty('expert'))

        self.btn_v3_momentum = QPushButton("Momentum")
        self.btn_v3_momentum.clicked.connect(lambda: self.switch_difficulty('v3_momentum'))
        
        self.btn_super_expert = QPushButton("Super Expert")
        self.btn_super_expert.clicked.connect(lambda: self.switch_difficulty('super_expert'))
        
        self.difficulty_btns = {
            'easy': self.btn_easy,
            'normal': self.btn_normal,
            'hard': self.btn_hard,
            'expert': self.btn_expert,
            'v3_momentum': self.btn_v3_momentum,
            'super_expert': self.btn_super_expert,
        }
        self.update_difficulty_button_styles()

        self.music_btn = QPushButton()
        self.music_btn.setFixedSize(34, 34)
        self.music_btn.setToolTip("開關背景音樂")
        self.music_btn.setIcon(QIcon(resource_path("assets/music_icon.png")))
        self.music_btn.setIconSize(QSize(22, 22))
        self.music_btn.clicked.connect(self.toggle_music)
        self.music_effect = QGraphicsOpacityEffect()
        self.music_btn.setGraphicsEffect(self.music_effect)

        self.sound_btn = QPushButton()
        self.sound_btn.setFixedSize(34, 34)
        self.sound_btn.setToolTip("開關音效")
        self.sound_btn.setIcon(QIcon(resource_path("assets/sound_icon.png")))
        self.sound_btn.setIconSize(QSize(22, 22))
        self.sound_btn.clicked.connect(self.toggle_sound)
        self.sound_effect = QGraphicsOpacityEffect()
        self.sound_btn.setGraphicsEffect(self.sound_effect)

        audio_button_style = """
            QPushButton {
                background-color: #E7E9ED;
                border: 1px solid rgba(255, 255, 255, 160);
                border-radius: 8px;
                padding: 3px;
            }
            QPushButton:hover {
                background-color: #F5F6F8;
            }
            QPushButton:pressed {
                background-color: #D4D7DD;
            }
        """
        self.music_btn.setStyleSheet(audio_button_style)
        self.sound_btn.setStyleSheet(audio_button_style)
        
        top_bar_layout.addWidget(self.info_btn)
        top_bar_layout.addWidget(self.btn_easy)
        top_bar_layout.addWidget(self.btn_normal)
        top_bar_layout.addWidget(self.btn_hard)
        top_bar_layout.addWidget(self.btn_expert)
        top_bar_layout.addWidget(self.btn_v3_momentum)
        top_bar_layout.addWidget(self.btn_super_expert)
        top_bar_layout.addStretch()
        top_bar_layout.addWidget(self.music_btn)
        top_bar_layout.addWidget(self.sound_btn)
        
        root_layout.addLayout(top_bar_layout)
        root_layout.addLayout(layout)
        
        main_widget.setLayout(root_layout)
        self.setCentralWidget(main_widget)

        self.update_ui()
        self.update_checklist()
        
        # Overlay for generator
        self.overlay_widget = QWidget(self.board_view)
        self.overlay_widget.setStyleSheet("background-color: rgba(0, 0, 0, 180);")
        self.overlay_layout = QVBoxLayout(self.overlay_widget)
        self.overlay_label = QLabel("生成中...")
        self.overlay_label.setStyleSheet("color: white; font-size: 24px; font-weight: bold; background: transparent;")
        self.overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cancel_generation_btn = QPushButton("取消生成")
        self.cancel_generation_btn.clicked.connect(self.cancel_board_generation)
        self.cancel_generation_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 230);
                color: #20242A;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: 700;
                padding: 10px 18px;
            }
            QPushButton:hover {
                background-color: white;
            }
            QPushButton:pressed {
                background-color: #D7DADF;
            }
            QPushButton:disabled {
                background-color: rgba(255, 255, 255, 120);
                color: #666A72;
            }
        """)
        self.overlay_layout.addWidget(self.overlay_label)
        self.overlay_layout.addWidget(self.cancel_generation_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.overlay_widget.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'overlay_widget'):
            self.overlay_widget.resize(self.board_view.size())

    def show_mode_info(self):
        QMessageBox.information(
            self,
            "模式說明",
            "Easy：固定棋盤，規則最單純，適合先熟悉機器人的滑行方式與目標順序。\n\n"
            "Normal：棋盤會有一些變化，路線不一定直覺，適合想要多一點挑戰的玩家。\n\n"
            "Hard：加入 Silver 機器人與更複雜的牆面配置，常常需要先移動其他機器人來鋪路。\n\n"
            "Expert：會出現彩色斜牆。不同顏色的機器人面對斜牆時反應不同，解題時要多留意反射與穿越。\n\n"
            "V3 Momentum：動量原型模式。機器人滑行後撞到另一台機器人時，會把已移動格數轉成同方向推動距離；撞牆會吸收剩餘動量。\n\n"
            "Super Expert：大型 32x32 高難度地圖，思考時間可能更長。生成或載入後建議先存檔。"
        )

    # ====== Audio Handlers ======
    def find_bgm_files(self):
        music_dir = resource_path('assets/music')
        patterns = ['BGM_*.mp4', 'BGM_*.m4a', 'BGM_*.wav', 'BGM_*.mp3']
        files = []
        for pattern in patterns:
            files.extend(glob.glob(os.path.join(music_dir, pattern)))
        return sorted(set(files), key=lambda path: os.path.basename(path).lower())

    def init_audio(self):
        self.bgm_player = QMediaPlayer(self)
        self.bgm_audio_output = QAudioOutput(self)
        self.bgm_audio_output.setVolume(0.35)
        self.bgm_player.setAudioOutput(self.bgm_audio_output)
        self.bgm_player.mediaStatusChanged.connect(self.on_bgm_media_status_changed)

        sound_files = {
            'move': 'assets/music/RobotFly.wav',
            'target': 'assets/music/GetTarget.wav',
            'finish': 'assets/music/GameFinish.wav',
        }
        for name, relative_path in sound_files.items():
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(resource_path(relative_path)))
            effect.setLoopCount(1)
            effect.setVolume(0.65)
            self.sound_effects[name] = effect

    def on_bgm_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.music_enabled:
            self.bgm_index = (self.bgm_index + 1) % len(self.bgm_files)
            self.start_bgm()

    def start_bgm(self):
        if not self.music_enabled or not self.bgm_player:
            return
        if not self.bgm_files:
            return
        bgm_path = self.bgm_files[self.bgm_index % len(self.bgm_files)]
        if not os.path.exists(bgm_path):
            return
        self.bgm_player.setSource(QUrl.fromLocalFile(bgm_path))
        self.bgm_player.play()

    def stop_bgm(self):
        if self.bgm_player:
            self.bgm_player.stop()

    def play_sound(self, name):
        if not self.sound_enabled:
            return
        effect = self.sound_effects.get(name)
        if effect:
            effect.stop()
            effect.play()

    def toggle_music(self):
        self.music_enabled = not self.music_enabled
        if self.music_enabled:
            self.start_bgm()
        else:
            self.stop_bgm()
        self.update_audio_button_states()
        self.save_audio_settings()

    def toggle_sound(self):
        self.sound_enabled = not self.sound_enabled
        self.update_audio_button_states()
        self.save_audio_settings()

    def update_audio_button_states(self):
        if hasattr(self, 'music_effect'):
            self.music_effect.setOpacity(1.0 if self.music_enabled else 0.2)
        if hasattr(self, 'sound_effect'):
            self.sound_effect.setOpacity(1.0 if self.sound_enabled else 0.2)

    def save_audio_settings(self):
        self.engine.save_settings(
            self.get_save_path(),
            {
                'music_enabled': self.music_enabled,
                'sound_enabled': self.sound_enabled,
            },
        )

    # ====== Solver UI Handlers ======
    def toggle_solver_panel(self):
        if self.eye_btn.isChecked():
            self.eye_btn.setText("隱藏提示面板")
            self.solver_panel.show()
        else:
            self.eye_btn.setText("顯示提示面板")
            self.solver_panel.hide()
            
    def toggle_solution_path(self):
        if not self.show_path_btn.isEnabled():
            return
        self.solution_path_visible = not self.solution_path_visible
        if self.solution_path_visible:
            self.solver_path_lbl.show()
            self.show_path_btn.setText("隱藏解答路徑")
        else:
            self.solver_path_lbl.hide()
            self.show_path_btn.setText("顯示解答路徑")

    def trigger_solver(self):
        if self.active_solver_thread and self.active_solver_thread.isRunning():
            self.active_solver_thread.cancel()
            self.calc_btn.setEnabled(False)
            self.solver_steps_lbl.setText("正在取消計算...")
            return

        self.solver_task_id += 1
        self.calc_btn.setEnabled(True)
        self.calc_btn.setText("取消計算")
        self.solver_dots = 0
        self.solver_steps_lbl.setText("計算中.")
        self.solver_path_lbl.setText("")
        self.solver_path_lbl.hide()
        self.solution_path_visible = False
        self.show_path_btn.setText("顯示解答路徑（先按計算）")
        self.show_path_btn.setEnabled(False)
        self.solver_timer.start(350)

        target_name, target_pos = self.engine.get_current_target()
        color_name, _ = target_name.split('_')

        thread = SolverThread(
            self.solver_task_id,
            self.engine.board,
            self.engine.start_robots.copy(),
            color_name,
            target_pos,
            grid_size=self.engine.grid_size,
            diagonal_walls=self.engine.diagonal_walls,
            movement_mode=self.engine._solver_movement_mode(),
        )
        self.active_solver_thread = thread
        thread.finished_signal.connect(self.on_solver_finished)
        thread.progress_signal.connect(self.on_solver_progress)
        thread.finished.connect(thread.deleteLater)

        if not hasattr(self, 'active_threads'):
            self.active_threads = set()
        self.active_threads.add(thread)
        thread.finished.connect(lambda: self.active_threads.discard(thread) if thread in self.active_threads else None)
        thread.start()

    def update_solver_progress_text(self):
        self.solver_dots = (self.solver_dots % 3) + 1
        self.solver_steps_lbl.setText("計算中" + "." * self.solver_dots)

    def on_solver_progress(self, expanded, depth):
        pass

    def on_solver_finished(self, task_id, steps, path):
        if task_id != self.solver_task_id:
            return

        self.solver_timer.stop()
        self.calc_btn.setEnabled(True)
        self.calc_btn.setText("⚙️ 開始計算最佳解")
        self.active_solver_thread = None

        if steps == -1:
            self.solver_steps_lbl.setText("最低步數: 無解")
            self.show_path_btn.setEnabled(False)
            self.show_path_btn.setText("顯示解答路徑（先按計算）")
            return
        if steps == -2:
            self.solver_steps_lbl.setText("已取消計算")
            self.show_path_btn.setEnabled(False)
            self.show_path_btn.setText("顯示解答路徑（先按計算）")
            return

        color_hex = {
            'Red': '#ff5555',
            'Blue': '#55aaff',
            'Green': '#55ff55',
            'Yellow': '#ffff55',
            'Silver': '#dddddd',
        }
        arrow_map = {'top': '↑', 'bottom': '↓', 'left': '←', 'right': '→'}
        html_path = []
        for color, direction in path:
            hc = color_hex.get(color, 'white')
            arr = arrow_map.get(direction, direction)
            html_path.append(
                f"<span style='color:{hc}; font-family: Arial, sans-serif; "
                f"font-size: 20px; font-weight: bold;'>{arr}</span>"
            )

        self.solver_steps_lbl.setText(f"最低步數: {steps} 步")
        self.show_path_btn.setEnabled(True)
        self.show_path_btn.setText("顯示解答路徑")
        self.solution_path_visible = False
        self.solver_path_lbl.hide()
        self.solver_path_lbl.setText(" ".join(html_path))

    # ====== Timer Methods ======
    def toggle_timer(self):
        if self.timer_running:
            self.qtimer.stop()
            self.timer_running = False
            self.apply_timer_style('paused')
        else:
            if self.timer_seconds == 0:
                self.timer_seconds = 90
                self.update_timer_display()
            self.flash_timer.stop()
            self.qtimer.start(1000)
            self.timer_running = True
            self.apply_timer_style('running')

    def reset_timer(self):
        self.qtimer.stop()
        self.flash_timer.stop()
        self.timer_running = False
        self.timer_seconds = 90
        self.update_timer_display()
        self.apply_timer_style('idle')

    def timer_tick(self):
        if self.timer_seconds > 0:
            self.timer_seconds -= 1
            self.update_timer_display()
            if self.timer_seconds == 0:
                self.qtimer.stop()
                self.timer_running = False
                self.flash_count = 0
                self.flash_timer.start(200) # flash every 200ms
        else:
            self.qtimer.stop()

    def update_timer_display(self):
        m = self.timer_seconds // 60
        s = self.timer_seconds % 60
        self.time_display.setText(f"{m:02d}:{s:02d}")

    def flash_tick(self):
        self.flash_count += 1
        if self.flash_count % 2 == 1:
            self.time_display.setStyleSheet("font-size: 32px; color: #FFFFFF; background-color: rgba(255,50,50,200);")
        else:
            self.time_display.setStyleSheet("font-size: 32px; color: #FFD700; background-color: transparent;")
            
        if self.flash_count >= 6: # 3 full flashes
            self.flash_timer.stop()
            self.apply_timer_style('idle')

    def apply_timer_style(self, state='idle'):
        styles = {
            'running': "font-size: 32px; color: #6DFFB0; background-color: rgba(24, 145, 91, 120); border-radius: 8px; padding: 2px 8px;",
            'paused': "font-size: 32px; color: #FFD86B; background-color: rgba(255, 187, 51, 55); border-radius: 8px; padding: 2px 8px;",
            'idle': "font-size: 32px; color: #FFD700; background-color: transparent; border-radius: 8px; padding: 2px 8px;",
        }
        self.time_display.setStyleSheet(styles.get(state, styles['idle']))

    # ====== Game Logic UI ======
    def update_ui(self, clear_solver=False):
        self.steps_label.setText(f"已嘗試: {self.engine.steps}")

        target_name, _ = self.engine.get_current_target()
        pm = self.board_view.get_token_pixmap(target_name, 100)
        self.target_image.setPixmap(pm)
        self.board_view.update_current_target_highlight()
        self.win_count_lbl.setText(f"破關次數: {self.engine.win_count}")

        if clear_solver:
            self.clear_solver_panel()

    def clear_solver_panel(self):
        self.solver_task_id += 1
        if self.active_solver_thread and self.active_solver_thread.isRunning():
            self.active_solver_thread.cancel()
            self.active_solver_thread = None
        self.solver_timer.stop()
        self.calc_btn.setEnabled(True)
        self.calc_btn.setText("⚙️ 開始計算最佳解")
        self.solver_steps_lbl.setText("")
        self.show_path_btn.setEnabled(False)
        self.show_path_btn.setText("顯示解答路徑（先按計算）")
        self.solution_path_visible = False
        self.solver_path_lbl.setText("")
        self.solver_path_lbl.hide()

    # ====== Admin Handlers ======
    def on_win_count_clicked(self):
        self.win_count_clicks += 1
        if not hasattr(self, 'win_count_timer'):
            self.win_count_timer = QTimer()
            self.win_count_timer.setSingleShot(True)
            self.win_count_timer.timeout.connect(self.reset_win_count_clicks)
        self.win_count_timer.start(800)

        if self.win_count_clicks >= 5:
            self.win_count_clicks = 0
            self.show_record_admin_menu()

    def show_record_admin_menu(self):
        menu = QMenu(self)
        clear_action = menu.addAction("清除遊戲紀錄檔案")
        adjust_action = menu.addAction("手動調整破關次數")
        action = menu.exec(self.win_count_lbl.mapToGlobal(self.win_count_lbl.rect().bottomLeft()))

        if action == clear_action:
            reply = QMessageBox.question(
                self,
                "清除紀錄",
                "確定要清除整個遊戲紀錄嗎？\n這會刪除五個難度的存檔槽與破關次數。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                if self.engine.clear_all_records(self.get_save_path()):
                    legacy_path = self.get_legacy_save_path()
                    if os.path.exists(legacy_path):
                        try:
                            os.remove(legacy_path)
                        except Exception:
                            pass
                    self.board_view.full_redraw()
                    self.update_difficulty_button_styles()
                    self.update_ui(clear_solver=True)
                    self.update_checklist()
                    self.reset_timer()
                    self.save_audio_settings()
                    QMessageBox.information(self, "清除完成", "遊戲紀錄已清除。")
                else:
                    QMessageBox.warning(self, "錯誤", "清除紀錄失敗。")
        elif action == adjust_action:
            value, ok = QInputDialog.getInt(
                self,
                "調整破關次數",
                "破關次數：",
                self.engine.win_count,
                0,
                999999,
                1,
            )
            if ok:
                self.engine.win_count = value
                self.update_ui()
                self.save_game_silent()

    def reset_win_count_clicks(self):
        self.win_count_clicks = 0

    def update_checklist(self):
        for name, lbl in self.cl_icons.items():
            effect = lbl.graphicsEffect()
            effect.setOpacity(1.0 if name in self.engine.completed_targets else 0.3)

    def undo_move(self):
        if self.engine.undo():
            self.board_view.highlight_item.hide()
            self.board_view.selected_color = None
            self.board_view.draw_robots()
            self.board_view.update_arrows()
            self.update_ui()

    def reset_game(self):
        self.engine.reset_game()
        self.board_view.highlight_item.hide()
        self.board_view.selected_color = None
        self.board_view.draw_robots()
        self.test_mode_btn.setChecked(False)
        self.toggle_test_mode()
        self.update_ui(clear_solver=True)
        self.update_checklist()
        self.reset_timer()

    def next_target(self):
        mark_completed = self.engine.check_win()
        if not mark_completed:
            reply = QMessageBox.question(
                self,
                "切換目標",
                "目前還沒有到達目標。確定要切換到下一個目標嗎？\n目前目標不會被算完成，之後仍然需要抵達。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return
        self.do_next_target(mark_completed=mark_completed)

    def do_next_target(self, mark_completed=True):
        if self.engine.difficulty_mode == 'v3_momentum':
            self.start_momentum_target_pick(
                mark_completed=mark_completed,
                exclude_current=not mark_completed,
                show_overlay=True,
                defer_apply=False,
            )
            return

        cleared = self.engine.next_target(mark_completed=mark_completed)
        if cleared:
            self.play_sound('finish')
            QMessageBox.information(self, "恭喜", "恭喜破關！準備開始下一輪。")
            self.engine.reset_game(full_reset=False)
            self.board_view.highlight_item.hide()
            self.board_view.selected_color = None
            self.board_view.draw_robots()
            self.save_game_silent()

        self.update_ui(clear_solver=True)
        self.update_checklist()
        if not self.engine.test_mode:
            self.target_label.setText("目前目標")
            self.target_label.setStyleSheet("color: #EEEEEE;")

    def check_win(self):
        if self.engine.check_win():
            if self.engine.test_mode:
                self.target_label.setText("已抵達目標（試走）")
                self.target_label.setStyleSheet("color: #FFAA00;")
            else:
                self.setStyleSheet("QMainWindow { background-color: #1A4A1A; color: #FFFFFF; font-family: 'Segoe UI', Arial; }")
                self.target_label.setText("成功！")
                self.target_label.setStyleSheet("color: #55FF55;")
                self.play_sound('target')
                if self.engine.difficulty_mode == 'v3_momentum':
                    self.start_momentum_target_pick(
                        mark_completed=True,
                        exclude_current=False,
                        show_overlay=False,
                        defer_apply=True,
                    )
                if not hasattr(self, 'success_timer'):
                    self.success_timer = QTimer(self)
                    self.success_timer.timeout.connect(self.success_tick)
                self.success_ticks = 0
                self.success_timer.start(100)

    def success_tick(self):
        self.success_ticks += 1
        target_pick_ready = (
            self.engine.difficulty_mode != 'v3_momentum'
            or self.pending_momentum_target_pick is not None
        )
        if self.success_ticks >= 30 and target_pick_ready:
            self.success_timer.stop()
            self.set_default_style()
            self.auto_next()
        else:
            uncompleted = [
                name for name, _ in self.engine.targets
                if not self.engine.is_target_retired(name) and name != self.engine.get_current_target()[0]
            ]
            random_target = random.choice(uncompleted) if uncompleted else self.engine.targets[0][0]
            pm = self.board_view.get_token_pixmap(random_target, 100)
            self.target_image.setPixmap(pm)

    def auto_next(self):
        if not self.engine.test_mode:
            if self.engine.difficulty_mode == 'v3_momentum':
                if self.pending_momentum_target_pick is not None:
                    self.apply_momentum_target_pick(self.pending_momentum_target_pick)
                else:
                    self.waiting_for_momentum_target_pick = True
                    self.show_target_pick_overlay()
                return
            self.do_next_target(mark_completed=True)

    def show_target_pick_overlay(self):
        self.set_buttons_enabled(False)
        self.overlay_widget.resize(self.board_view.size())
        self.overlay_label.setText("抽選目標中...")
        self.cancel_generation_btn.hide()
        self.overlay_widget.show()

    def hide_target_pick_overlay(self):
        self.overlay_widget.hide()
        self.cancel_generation_btn.show()
        self.set_buttons_enabled(True)

    def start_momentum_target_pick(self, mark_completed=True, exclude_current=False, show_overlay=False, defer_apply=False):
        if self.active_target_picker_thread and self.active_target_picker_thread.isRunning():
            return

        current_target_name = self.engine.get_current_target()[0]
        completed_targets = set(self.engine.completed_targets)
        if mark_completed:
            completed_targets.add(current_target_name)

        if mark_completed and len(completed_targets) >= len(self.engine.targets):
            self.pending_momentum_target_pick = {
                'mark_completed': mark_completed,
                'completed_targets': completed_targets,
                'cleared': True,
                'defer_apply': defer_apply,
            }
            if not defer_apply:
                if show_overlay:
                    self.show_target_pick_overlay()
                self.apply_momentum_target_pick(self.pending_momentum_target_pick)
            return

        self.pending_momentum_target_pick = None
        self.waiting_for_momentum_target_pick = False
        self.target_picker_task_id += 1

        if show_overlay:
            self.show_target_pick_overlay()

        thread = TargetPickerThread(
            self.target_picker_task_id,
            self.engine.board,
            self.engine.robots.copy(),
            self.engine.targets,
            completed_targets,
            self.engine.current_target_idx,
            grid_size=self.engine.grid_size,
            diagonal_walls=self.engine.diagonal_walls,
            movement_mode=self.engine._solver_movement_mode(),
            exclude_current=exclude_current,
        )
        thread.defer_apply = defer_apply
        thread.mark_completed = mark_completed
        thread.completed_targets = completed_targets
        self.active_target_picker_thread = thread
        thread.finished_signal.connect(self.on_momentum_target_pick_finished)
        thread.finished.connect(thread.deleteLater)

        if not hasattr(self, 'active_threads'):
            self.active_threads = set()
        self.active_threads.add(thread)
        thread.finished.connect(lambda: self.active_threads.discard(thread) if thread in self.active_threads else None)
        thread.start()

    def on_momentum_target_pick_finished(self, task_id, next_idx):
        if task_id != self.target_picker_task_id:
            return

        thread = self.active_target_picker_thread
        self.active_target_picker_thread = None
        pick = {
            'mark_completed': getattr(thread, 'mark_completed', True),
            'completed_targets': getattr(thread, 'completed_targets', set(self.engine.completed_targets)),
            'next_idx': next_idx,
            'cleared': False,
            'defer_apply': getattr(thread, 'defer_apply', False),
        }
        self.pending_momentum_target_pick = pick

        if self.waiting_for_momentum_target_pick or not pick['defer_apply']:
            self.apply_momentum_target_pick(pick)

    def apply_momentum_target_pick(self, pick):
        self.pending_momentum_target_pick = None
        self.waiting_for_momentum_target_pick = False
        self.engine.completed_targets = set(pick.get('completed_targets', self.engine.completed_targets))

        if pick.get('cleared'):
            self.hide_target_pick_overlay()
            self.play_sound('finish')
            QMessageBox.information(self, "恭喜", "恭喜破關！準備開始下一輪。")
            self.engine.win_count += 1
            self.engine.reset_to_v3_momentum_board(full_reset=False)
            self.board_view.highlight_item.hide()
            self.board_view.selected_color = None
            self.board_view.full_redraw()
            self.save_game_silent()
        else:
            self.engine.current_target_idx = pick['next_idx']
            self.engine.steps = 0
            self.engine.move_history = []
            self.engine.last_move_changed_colors = []
            self.engine.last_move_animation_steps = []
            self.engine.start_robots = self.engine.robots.copy()
            self.hide_target_pick_overlay()

        self.update_ui(clear_solver=True)
        self.update_checklist()
        if not self.engine.test_mode:
            self.target_label.setText("目前目標")
            self.target_label.setStyleSheet("color: #EEEEEE;")

    # ====== Test Mode ======
    def toggle_test_mode(self):
        is_test = self.test_mode_btn.isChecked()
        if not is_test:
            self.revert_test_mode()

        self.engine.toggle_test_mode(is_test)
        if is_test:
            self.set_test_mode_style()
            self.full_revert_btn.show()
            self.target_label.setText("試走模式啟動中")
            self.target_label.setStyleSheet("color: #FFAA00;")
        else:
            self.set_default_style()
            self.full_revert_btn.hide()
            self.target_label.setText("目前目標")
            self.target_label.setStyleSheet("color: #EEEEEE;")

    def revert_test_mode(self):
        if self.engine.revert_test_mode():
            self.board_view.highlight_item.hide()
            self.board_view.selected_color = None
            self.board_view.draw_robots()
            self.board_view.update_arrows()
            self.update_ui()

    def get_save_dir(self):
        base_dir = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return os.path.join(base_dir, 'RicochetRobots')

    def get_save_path(self):
        return os.path.join(self.get_save_dir(), 'save.json')

    def get_legacy_save_path(self):
        return os.path.join(os.path.expanduser('~'), 'ricochet_robots_save.json')

    def _migrate_legacy_save_if_needed(self):
        new_path = self.get_save_path()
        legacy_path = self.get_legacy_save_path()
        if os.path.exists(new_path) or not os.path.exists(legacy_path):
            return
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.copy2(legacy_path, new_path)
        except Exception:
            pass

    def save_game_silent(self):
        self._migrate_legacy_save_if_needed()
        return self.engine.save_state(self.get_save_path())

    def save_game(self):
        if self.save_game_silent():
            QMessageBox.information(self, "提示", f"已保存 {self.engine.difficulty_mode.replace('_', ' ').title()} 進度。")
        else:
            QMessageBox.warning(self, "錯誤", "存檔失敗！")

    def load_game(self):
        self._migrate_legacy_save_if_needed()
        if self.engine.load_state(self.get_save_path()):
            self.refresh_board_after_state_change(clear_solver=True)
            QMessageBox.information(self, "提示", "讀取存檔成功！")
        else:
            QMessageBox.warning(self, "錯誤", "找不到目前難度的存檔槽，或讀取失敗。")

    def switch_difficulty(self, mode: str):
        if self.gen_thread_is_running():
            return

        if self.engine.difficulty_mode == mode:
            reply = QMessageBox.question(
                self,
                "重新生成地圖",
                f"要重新生成 {mode.replace('_', ' ').title()} 的新地圖嗎？\n目前尚未存檔的進度會被覆蓋。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return
            self.save_game_silent()
            self.start_new_difficulty_board(mode)
            return

        self.save_game_silent()

        if self.engine.has_saved_slot(self.get_save_path(), mode):
            if self.engine.load_state(self.get_save_path(), mode=mode):
                self.refresh_board_after_state_change(clear_solver=True)
                self.save_game_silent()
                return

        self.start_new_difficulty_board(mode)

    def start_new_difficulty_board(self, mode):
        if mode == 'easy':
            self.engine.reset_to_static_board()
            self.refresh_board_after_state_change(clear_solver=True)
            self.save_game_silent()
        elif mode == 'v3_momentum':
            self.engine.reset_to_v3_momentum_board()
            self.refresh_board_after_state_change(clear_solver=True)
            self.save_game_silent()
        elif mode == 'super_expert':
            self.start_super_expert()
        else:
            self.start_board_generation(mode)

    def refresh_board_after_state_change(self, clear_solver=False):
        self.update_difficulty_button_styles()
        self.board_view.full_redraw()
        self.update_ui(clear_solver=clear_solver)
        self.update_checklist()
        self.reset_timer()

    def update_difficulty_button_styles(self):
        styles = {
            'easy': ('background-color: #4CAF50;', 'background-color: rgba(76,175,80,0.3);'),
            'normal': ('background-color: #2196F3;', 'background-color: rgba(33,150,243,0.3);'),
            'hard': ('background-color: #FF9800;', 'background-color: rgba(255,152,0,0.3);'),
            'expert': ('background-color: #F44336;', 'background-color: rgba(244,67,54,0.3);'),
            'v3_momentum': ('background-color: #00A896;', 'background-color: rgba(0,168,150,0.3);'),
            'super_expert': ('background-color: #9C27B0;', 'background-color: rgba(156,39,176,0.3);'),
        }
        for mode, btn in self.difficulty_btns.items():
            active_style, inactive_style = styles[mode]
            if mode == self.engine.difficulty_mode:
                btn.setStyleSheet(f'{active_style} color: white; font-weight: bold; padding: 8px 15px; border-radius: 5px; border: 3px solid white;')
            else:
                btn.setStyleSheet(f'{inactive_style} color: rgba(255,255,255,0.5); font-weight: bold; padding: 8px 15px; border-radius: 5px;')

    def set_buttons_enabled(self, enabled):
        self.undo_btn.setEnabled(enabled)
        self.next_btn.setEnabled(enabled)
        self.reset_btn.setEnabled(enabled)
        self.test_mode_btn.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)
        self.load_btn.setEnabled(enabled)
        self.info_btn.setEnabled(enabled)
        if hasattr(self, 'music_btn'):
            self.music_btn.setEnabled(enabled)
        if hasattr(self, 'sound_btn'):
            self.sound_btn.setEnabled(enabled)
        for btn in self.difficulty_btns.values():
            btn.setEnabled(enabled)

    def gen_thread_is_running(self):
        return hasattr(self, 'gen_thread') and self.gen_thread is not None and self.gen_thread.isRunning()

    def _restore_pending_generation_state(self):
        if self.pending_generation_previous_state:
            self.engine._apply_state(self.pending_generation_previous_state)
        self.pending_generation_previous_state = None
        self.pending_generation_mode = None

    def start_super_expert(self):
        self.pending_generation_previous_state = self.engine._serialize_current_state()
        self.set_buttons_enabled(False)
        self.overlay_widget.resize(self.board_view.size())
        self.overlay_label.setText("Super Expert 地圖載入中...")
        self.cancel_generation_btn.hide()
        self.overlay_widget.show()
        QApplication.processEvents()

        maps_path = resource_path('assets/super_expert_maps.json')
        if not os.path.exists(maps_path):
            self.overlay_widget.hide()
            self.cancel_generation_btn.show()
            self.set_buttons_enabled(True)
            QMessageBox.warning(self, 'Super Expert', '找不到預生成地圖資料 assets/super_expert_maps.json。')
            self._restore_pending_generation_state()
            self.refresh_board_after_state_change(clear_solver=True)
            return

        import json
        with open(maps_path, 'r', encoding='utf-8') as f:
            maps_list = json.load(f)
        if not maps_list:
            self.overlay_widget.hide()
            self.cancel_generation_btn.show()
            self.set_buttons_enabled(True)
            QMessageBox.warning(self, 'Super Expert', 'Super Expert 地圖資料為空。')
            self._restore_pending_generation_state()
            self.refresh_board_after_state_change(clear_solver=True)
            return

        chosen = random.choice(maps_list)
        if 'diagonal_walls' in chosen:
            converted = {}
            for k, v in chosen['diagonal_walls'].items():
                if isinstance(k, list):
                    converted[tuple(k)] = v
                elif isinstance(k, str):
                    import ast
                    try:
                        converted[ast.literal_eval(k)] = v
                    except Exception:
                        converted[k] = v
                else:
                    converted[k] = v
            chosen['diagonal_walls'] = converted
        if 'targets' in chosen:
            chosen['targets'] = {name: tuple(pos) for name, pos in chosen['targets'].items()}
        if 'robot_positions' in chosen:
            chosen['robot_positions'] = {col: tuple(pos) for col, pos in chosen['robot_positions'].items()}
        chosen['difficulty'] = 'super_expert'

        self.engine.load_generated_board(chosen)
        self.pending_generation_previous_state = None
        self.pending_generation_mode = None
        self.overlay_widget.hide()
        self.cancel_generation_btn.show()
        self.set_buttons_enabled(True)
        self.refresh_board_after_state_change(clear_solver=True)
        self.save_game_silent()
        self.show_high_difficulty_save_reminder()

    def start_board_generation(self, mode):
        self.pending_generation_previous_state = self.engine._serialize_current_state()
        self.pending_generation_mode = mode
        self.engine.difficulty_mode = mode
        self.update_difficulty_button_styles()
        self.set_buttons_enabled(False)
        self.overlay_widget.resize(self.board_view.size())
        self.overlay_widget.show()
        self.cancel_generation_btn.show()
        self.overlay_label.setText("生成中...")

        self.gen_thread = BoardGeneratorThread(mode)
        self.gen_thread.progress_signal.connect(self.overlay_label.setText)
        self.gen_thread.board_ready.connect(self.on_board_generated)
        self.gen_thread.start()

    def cancel_board_generation(self):
        if self.gen_thread_is_running():
            self.overlay_label.setText("正在取消生成...")
            self.cancel_generation_btn.setEnabled(False)
            self.gen_thread.cancel()

    def on_board_generated(self, board_data):
        self.overlay_widget.hide()
        self.cancel_generation_btn.setEnabled(True)
        self.set_buttons_enabled(True)

        if board_data.get('__cancelled__'):
            self._restore_pending_generation_state()
            self.refresh_board_after_state_change(clear_solver=True)
            QMessageBox.information(self, "已取消", "地圖生成已取消，已保留原本盤面。")
            return

        if not board_data:
            self._restore_pending_generation_state()
            self.refresh_board_after_state_change(clear_solver=True)
            QMessageBox.warning(self, "生成失敗", "找不到符合可解性要求的地圖，請再試一次。")
            return

        self.engine.load_generated_board(board_data)
        completed_mode = self.engine.difficulty_mode
        self.pending_generation_previous_state = None
        self.pending_generation_mode = None
        self.refresh_board_after_state_change(clear_solver=True)
        self.save_game_silent()
        if completed_mode in ('expert', 'super_expert'):
            self.show_high_difficulty_save_reminder()

    def show_high_difficulty_save_reminder(self):
        QMessageBox.information(self, "記得存檔", "高難度地圖已生成，建議先按「存檔」保存目前地圖。")
if __name__ == '__main__':
    import ctypes
    from PyQt6.QtGui import QIcon
    try:
        myappid = 'ricochet.robots.game.1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass
        
    app = QApplication(sys.argv)
    
    icon_path = resource_path('assets/app_icon.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        
    window = MainWindow()
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
        
    window.show()
    sys.exit(app.exec())


