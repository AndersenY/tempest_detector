import numpy as np
import pyqtgraph as pg
from collections import deque
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QComboBox
from PyQt6.QtCore import Qt


class WaterfallWidget(QWidget):
    """Водопадная диаграмма (спектрограмма во времени)."""
    def __init__(self, max_rows: int = 200, db_range: tuple = (-120, -10)):
        super().__init__()
        self.buffer = deque(maxlen=max_rows)
        self.db_min, self.db_max = db_range
        self.decimation = 4  # прореживание для производительности
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        ctrl = QHBoxLayout()
        self.lbl_info = QLabel("Строк: 0 | Прореживание: x4")
        self.lbl_info.setStyleSheet("color: #aaa; font-size: 11px;")
        self.cmb_cmap = QComboBox()
        self.cmb_cmap.addItems(["Inferno", "Plasma", "Viridis", "Gray", "Turbo"])
        self.cmb_cmap.currentTextChanged.connect(self._update_colormap)
        ctrl.addWidget(self.lbl_info)
        ctrl.addStretch()
        ctrl.addWidget(self.cmb_cmap)
        layout.addLayout(ctrl)

        self.img = pg.ImageItem()
        self.img.setLevels((self.db_min, self.db_max))
        self._update_colormap("Inferno")
        layout.addWidget(self.img, 1)

    def append(self, spectrum_db: np.ndarray) -> None:
        if spectrum_db.ndim != 1:
            return
        dec = spectrum_db[::self.decimation]
        self.buffer.append(dec)
        self._render()

    def _render(self) -> None:
        if not self.buffer:
            return
        arr = np.array(self.buffer)
        self.img.setImage(arr, autoLevels=False)
        self.lbl_info.setText(f"Строк: {len(self.buffer)} | Прореживание: x{self.decimation}")

    def _update_colormap(self, name: str):
        cmap = pg.colormap.get(name)
        self.img.setColorMap(cmap)

    def clear(self):
        self.buffer.clear()
        self.img.setImage(np.zeros((0, 0)), autoLevels=False)

    def set_db_range(self, min_db: float, max_db: float):
        self.db_min, self.db_max = min_db, max_db
        self.img.setLevels((self.db_min, self.db_max))