"""
Temporary wall editor for Ricochet Robots maps.

Run:
    .\\venv\\Scripts\\python.exe scripts\\wall_editor.py

The exported JSON uses the same h_walls / v_walls schema as generated boards:
    h_walls: [row, col] is the wall between (row, col) and (row + 1, col)
    v_walls: [row, col] is the wall between (row, col) and (row, col + 1)
"""

import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QImage, QKeySequence, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def center_block_walls(grid_size):
    cx = grid_size // 2 - 1
    return {
        "h": {(cx - 1, cx), (cx - 1, cx + 1), (cx + 1, cx), (cx + 1, cx + 1)},
        "v": {(cx, cx - 1), (cx + 1, cx - 1), (cx, cx + 1), (cx + 1, cx + 1)},
    }


class WallCanvas(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_size = 16
        self.h_walls = set()
        self.v_walls = set()
        self.background = QPixmap()
        self.background_opacity = 0.45
        self.show_center_block = True
        self.hover_wall = None
        self.setMouseTracking(True)
        self.setMinimumSize(560, 560)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.reset_walls(include_center=True)

    def reset_walls(self, include_center=True):
        self.h_walls.clear()
        self.v_walls.clear()
        if include_center:
            center = center_block_walls(self.grid_size)
            self.h_walls.update(center["h"])
            self.v_walls.update(center["v"])
        self.hover_wall = None
        self.changed.emit()
        self.update()

    def set_grid_size(self, grid_size):
        self.grid_size = int(grid_size)
        self.reset_walls(include_center=self.show_center_block)

    def set_background_image(self, path):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            raise ValueError(f"Cannot load image: {path}")
        self.background = pixmap
        self.update()

    def board_rect(self):
        margin = 28
        size = min(self.width(), self.height()) - margin * 2
        size = max(120, size)
        x = (self.width() - size) / 2
        y = (self.height() - size) / 2
        return QRectF(x, y, size, size)

    def cell_size(self):
        return self.board_rect().width() / self.grid_size

    def wall_at_pos(self, pos):
        rect = self.board_rect()
        if not rect.contains(QPointF(pos)):
            return None

        cell = rect.width() / self.grid_size
        bx = (pos.x() - rect.left()) / cell
        by = (pos.y() - rect.top()) / cell
        threshold = max(0.14, min(0.24, 8 / cell))

        nearest_x = round(bx)
        nearest_y = round(by)
        vertical_dist = abs(bx - nearest_x)
        horizontal_dist = abs(by - nearest_y)

        candidates = []
        if 1 <= nearest_x <= self.grid_size - 1 and 0 <= by < self.grid_size:
            r = min(self.grid_size - 1, max(0, int(by)))
            c = nearest_x - 1
            candidates.append((vertical_dist, "v", (r, c)))

        if 1 <= nearest_y <= self.grid_size - 1 and 0 <= bx < self.grid_size:
            r = nearest_y - 1
            c = min(self.grid_size - 1, max(0, int(bx)))
            candidates.append((horizontal_dist, "h", (r, c)))

        if not candidates:
            return None

        dist, wall_type, wall = min(candidates, key=lambda item: item[0])
        if dist > threshold:
            return None
        return wall_type, wall

    def toggle_wall(self, wall_type, wall):
        target = self.h_walls if wall_type == "h" else self.v_walls
        if wall in target:
            target.remove(wall)
        else:
            target.add(wall)
        self.changed.emit()
        self.update()

    def mouseMoveEvent(self, event):
        self.hover_wall = self.wall_at_pos(event.position())
        self.update()

    def leaveEvent(self, event):
        self.hover_wall = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            wall = self.wall_at_pos(event.position())
            if wall:
                self.toggle_wall(*wall)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hover_wall = None
            self.update()
        else:
            super().keyPressEvent(event)

    def export_data(self):
        return {
            "grid_size": self.grid_size,
            "h_walls": [list(wall) for wall in sorted(self.h_walls)],
            "v_walls": [list(wall) for wall in sorted(self.v_walls)],
            "targets": {},
            "robot_positions": {},
            "difficulty": "custom",
            "notes": "Generated by scripts/wall_editor.py. Fill targets and robot_positions manually.",
        }

    def load_data(self, data):
        grid_size = int(data.get("grid_size", self.grid_size))
        self.grid_size = grid_size
        self.h_walls = {tuple(item) for item in data.get("h_walls", [])}
        self.v_walls = {tuple(item) for item in data.get("v_walls", [])}
        self.changed.emit()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#17191d"))

        rect = self.board_rect()
        cell = rect.width() / self.grid_size

        if not self.background.isNull():
            painter.save()
            painter.setOpacity(self.background_opacity)
            scaled = self.background.scaled(
                int(rect.width()),
                int(rect.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            sx = (scaled.width() - rect.width()) / 2
            sy = (scaled.height() - rect.height()) / 2
            painter.drawPixmap(rect, scaled, QRectF(sx, sy, rect.width(), rect.height()))
            painter.restore()
        else:
            painter.fillRect(rect, QColor("#23272f"))

        painter.setPen(QPen(QColor("#4a515f"), 1))
        for i in range(self.grid_size + 1):
            x = rect.left() + i * cell
            y = rect.top() + i * cell
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

        if self.show_center_block:
            cx = self.grid_size // 2 - 1
            center_rect = QRectF(rect.left() + cx * cell, rect.top() + cx * cell, 2 * cell, 2 * cell)
            painter.fillRect(center_rect, QColor(20, 20, 22, 210))
            painter.setPen(QPen(QColor("#d8dde8"), max(2, cell * 0.07)))
            painter.drawRect(center_rect)

        wall_pen = QPen(QColor("#f4f0df"), max(3, cell * 0.12))
        wall_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(wall_pen)

        for r, c in sorted(self.h_walls):
            y = rect.top() + (r + 1) * cell
            x1 = rect.left() + c * cell
            x2 = rect.left() + (c + 1) * cell
            painter.drawLine(QPointF(x1, y), QPointF(x2, y))

        for r, c in sorted(self.v_walls):
            x = rect.left() + (c + 1) * cell
            y1 = rect.top() + r * cell
            y2 = rect.top() + (r + 1) * cell
            painter.drawLine(QPointF(x, y1), QPointF(x, y2))

        border_pen = QPen(QColor("#f4f0df"), max(4, cell * 0.14))
        painter.setPen(border_pen)
        painter.drawRect(rect)

        if self.hover_wall:
            wall_type, (r, c) = self.hover_wall
            hover_pen = QPen(QColor("#ffb84d"), max(4, cell * 0.16))
            hover_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(hover_pen)
            if wall_type == "h":
                y = rect.top() + (r + 1) * cell
                painter.drawLine(QPointF(rect.left() + c * cell, y), QPointF(rect.left() + (c + 1) * cell, y))
            else:
                x = rect.left() + (c + 1) * cell
                painter.drawLine(QPointF(x, rect.top() + r * cell), QPointF(x, rect.top() + (r + 1) * cell))

        painter.setPen(QPen(QColor("#aeb6c6"), 1))
        painter.setFont(QFont("Consolas", 8))
        if cell >= 28:
            for i in range(self.grid_size):
                painter.drawText(QRectF(rect.left() + i * cell, rect.top() - 22, cell, 18), Qt.AlignmentFlag.AlignCenter, str(i))
                painter.drawText(QRectF(rect.left() - 24, rect.top() + i * cell, 22, cell), Qt.AlignmentFlag.AlignCenter, str(i))

    def save_png(self, path):
        image = QImage(self.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("transparent"))
        painter = QPainter(image)
        self.render(painter)
        painter.end()
        image.save(path)


class WallEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ricochet Robots Wall Editor")
        self.canvas = WallCanvas()
        self.status = QLabel()
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(4, 64)
        self.grid_spin.setValue(16)
        self.grid_spin.setSingleStep(2)
        self.grid_spin.valueChanged.connect(self.canvas.set_grid_size)

        self.center_checkbox = QCheckBox("Center block")
        self.center_checkbox.setChecked(True)
        self.center_checkbox.toggled.connect(self.set_center_block)

        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setValue(45)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.valueChanged.connect(self.set_opacity)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Grid"))
        toolbar.addWidget(self.grid_spin)
        toolbar.addWidget(self.center_checkbox)
        toolbar.addWidget(QLabel("Photo"))
        toolbar.addWidget(self.opacity_spin)

        for text, handler in [
            ("Open Photo", self.open_photo),
            ("Load JSON", self.load_json),
            ("Save JSON", self.save_json),
            ("Save PNG", self.save_png),
            ("Clear", self.clear_walls),
        ]:
            button = QPushButton(text)
            button.clicked.connect(handler)
            toolbar.addWidget(button)

        toolbar.addStretch(1)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addLayout(toolbar)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.status)
        self.setCentralWidget(root)

        save_action = QAction(self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_json)
        self.addAction(save_action)

        self.canvas.changed.connect(self.update_status)
        self.update_status()
        self.resize(900, 760)

    def set_center_block(self, checked):
        self.canvas.show_center_block = checked
        center = center_block_walls(self.canvas.grid_size)
        if checked:
            self.canvas.h_walls.update(center["h"])
            self.canvas.v_walls.update(center["v"])
        else:
            self.canvas.h_walls.difference_update(center["h"])
            self.canvas.v_walls.difference_update(center["v"])
        self.canvas.changed.emit()
        self.canvas.update()

    def set_opacity(self, value):
        self.canvas.background_opacity = value / 100
        self.canvas.update()

    def update_status(self):
        self.status.setText(
            f"grid={self.canvas.grid_size}  "
            f"h_walls={len(self.canvas.h_walls)}  "
            f"v_walls={len(self.canvas.v_walls)}  "
            "click an inner grid line to toggle a wall"
        )

    def open_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open board photo",
            ROOT_DIR,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*.*)",
        )
        if not path:
            return
        try:
            self.canvas.set_background_image(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Open Photo", str(exc))

    def load_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load wall JSON",
            ROOT_DIR,
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.canvas.load_data(data)
            self.grid_spin.blockSignals(True)
            self.grid_spin.setValue(self.canvas.grid_size)
            self.grid_spin.blockSignals(False)
        except Exception as exc:
            QMessageBox.warning(self, "Load JSON", str(exc))

    def save_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save wall JSON",
            os.path.join(ROOT_DIR, "dev_assets", "custom_walls.json"),
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.canvas.export_data(), f, ensure_ascii=False, indent=2)
            self.status.setText(f"Saved {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Save JSON", str(exc))

    def save_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save board preview",
            os.path.join(ROOT_DIR, "dev_assets", "custom_walls_preview.png"),
            "PNG files (*.png);;All files (*.*)",
        )
        if not path:
            return
        try:
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            self.canvas.save_png(path)
            self.status.setText(f"Saved {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Save PNG", str(exc))

    def clear_walls(self):
        self.canvas.reset_walls(include_center=self.center_checkbox.isChecked())


def main():
    app = QApplication(sys.argv)
    window = WallEditorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

