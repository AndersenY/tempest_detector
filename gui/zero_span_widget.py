import time
from collections import deque
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from gui.theme import DARK


class ZeroSpanWidget(QWidget):
    """
    Осциллографический вид — амплитуда (дБ) как функция времени.
    Отображается вместо панорамы спектра во время Zero Span мониторинга.
    """

    _MAX_POINTS = 300

    def __init__(self) -> None:
        super().__init__()
        self._buffer  = deque(maxlen=self._MAX_POINTS)
        self._times   = deque(maxlen=self._MAX_POINTS)
        self._t_start: float | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Шапка: частота слева, текущий уровень справа
        header = QHBoxLayout()
        self._lbl_title = QLabel("Zero Span")
        self._lbl_title.setStyleSheet(
            "color: #e0e0e0; font-size: 13px; font-weight: bold;"
        )
        self._lbl_current = QLabel("— дБ")
        self._lbl_current.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._lbl_current.setStyleSheet(
            "color: #4FC3F7; font-size: 16px; font-weight: bold; font-family: monospace;"
        )
        header.addWidget(self._lbl_title)
        header.addStretch()
        header.addWidget(self._lbl_current)
        layout.addLayout(header)

        # График
        self._pw = pg.PlotWidget()
        self._pw.setBackground("#1a1a2e")
        self._pw.showGrid(x=True, y=True, alpha=0.25)
        self._pw.setLabel("left",   "Уровень, дБ", color="#cccccc", size="11px")
        self._pw.setLabel("bottom", "Время, с",    color="#cccccc", size="11px")
        self._pw.getAxis("left").setTextPen("white")
        self._pw.getAxis("bottom").setTextPen("white")

        self._curve = self._pw.plot(
            [], [],
            pen=pg.mkPen("#4FC3F7", width=2),
        )
        # Пунктир — исходный уровень из статического измерения
        self._baseline = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen("#FF8F00", width=1.5, style=Qt.PenStyle.DashLine),
            label="Статический уровень",
            labelOpts={
                "color": "#FF8F00", "position": 0.98,
                "fill": pg.mkBrush(26, 26, 46, 180),
            },
        )
        self._pw.addItem(self._baseline)
        layout.addWidget(self._pw, 1)

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    def set_signal_info(self, freq_hz: float, baseline_db: float) -> None:
        """Установить заголовок и базовую линию перед стартом."""
        self._lbl_title.setText(
            f"Zero Span  —  <b>{freq_hz / 1e6:.4f} МГц</b>"
        )
        self._baseline.setValue(baseline_db)

    def add_point(self, amp_db: float) -> None:
        """Добавить очередную точку (вызывается из ZeroSpanWorker через Qt-сигнал)."""
        if self._t_start is None:
            self._t_start = time.monotonic()
        self._times.append(time.monotonic() - self._t_start)
        self._buffer.append(amp_db)
        self._refresh(amp_db)

    def clear(self) -> None:
        self._buffer.clear()
        self._times.clear()
        self._t_start = None
        self._curve.setData([], [])
        self._lbl_current.setText("— дБ")

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Тема оформления
    # ------------------------------------------------------------------

    def apply_theme(self, t: dict) -> None:
        self._lbl_title.setStyleSheet(
            f"color: {t['zs_title_fg']}; font-size: 13px; font-weight: bold;"
        )
        self._lbl_current.setStyleSheet(
            f"color: {t['zs_level_fg']}; font-size: 16px; font-weight: bold;"
            f" font-family: monospace;"
        )
        self._pw.setBackground(t["bg_zerospan"])
        self._pw.setLabel("left",   "Уровень, дБ", color=t["zs_axis_fg"], size="11px")
        self._pw.setLabel("bottom", "Время, с",    color=t["zs_axis_fg"], size="11px")
        self._pw.getAxis("left").setTextPen(t["zs_axis_fg"])
        self._pw.getAxis("bottom").setTextPen(t["zs_axis_fg"])

    def _refresh(self, current_db: float) -> None:
        t_arr = np.array(self._times)
        a_arr = np.array(self._buffer)
        self._curve.setData(t_arr, a_arr)
        self._lbl_current.setText(f"{current_db:+.1f} дБ")
        if len(a_arr) > 2:
            spread = max(a_arr.max() - a_arr.min(), 2.0)
            margin = spread * 0.15
            self._pw.setYRange(a_arr.min() - margin, a_arr.max() + margin, padding=0)
