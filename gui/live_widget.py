import time
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                              QLabel, QPushButton, QDoubleSpinBox)
from PyQt6.QtCore import Qt, pyqtSignal


class LiveWidget(QWidget):
    """
    Режим прямого эфира — живой спектр с Peak Hold и маркировкой частот.

    Метки (📌): включить режим кнопкой «Метка», затем кликнуть на график.
    Помеченные частоты хранятся в marked_freqs_mhz и доступны из MainWindow
    для последующего запуска панорамы.
    """

    freq_marked = pyqtSignal(float)    # МГц, при добавлении метки
    freq_selected = pyqtSignal(float)  # МГц, при клике вне режима меток кликом

    _DB_MIN = -95.0
    _DB_MAX = -40.0

    def __init__(self) -> None:
        super().__init__()
        self._peak_hold: np.ndarray | None = None
        self._show_peak = True
        self._x_initialized = False
        self._last_time = time.time()
        self._frame_count = 0
        self._marked_lines: list = []
        self.marked_freqs_mhz: list[float] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_plot(), 1)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background-color: #141418; border-bottom: 1px solid #2a2a2a;")
        bar.setFixedHeight(36)

        lo = QHBoxLayout(bar)
        lo.setContentsMargins(8, 4, 8, 4)
        lo.setSpacing(10)

        _btn = """
            QPushButton {
                background-color: #252525; color: #bbb; border: 1px solid #3a3a3a;
                padding: 2px 10px; border-radius: 3px; font-size: 11px;
            }
            QPushButton:hover   { background-color: #333; }
            QPushButton:checked { background-color: #1565C0; color: white; border-color: #1976D2; }
        """
        _btn_mark = """
            QPushButton {
                background-color: #252525; color: #bbb; border: 1px solid #3a3a3a;
                padding: 2px 10px; border-radius: 3px; font-size: 11px;
            }
            QPushButton:hover   { background-color: #333; }
            QPushButton:checked { background-color: #E65100; color: white; border-color: #FF6D00; }
        """
        _spin_style = """
            QDoubleSpinBox {
                background-color: #252525; color: #bbb; border: 1px solid #3a3a3a;
                border-radius: 3px; padding: 1px 2px; font-size: 11px;
            }
        """
        _lbl = "color: #666; font-size: 11px;"

        self.btn_peak = QPushButton("Peak Hold")
        self.btn_peak.setCheckable(True)
        self.btn_peak.setChecked(True)
        self.btn_peak.setStyleSheet(_btn)
        self.btn_peak.toggled.connect(self._on_peak_toggle)

        self.btn_reset_peak = QPushButton("⟲ Сброс Peak")
        self.btn_reset_peak.setStyleSheet(_btn)
        self.btn_reset_peak.clicked.connect(self.reset_peak)

        self.btn_mark = QPushButton("📌 Метка")
        self.btn_mark.setCheckable(True)
        self.btn_mark.setStyleSheet(_btn_mark)
        self.btn_mark.setToolTip("Включить режим меток: кликните на спектр для пометки частоты")

        self.btn_clear_marks = QPushButton("✕ Метки")
        self.btn_clear_marks.setStyleSheet(_btn)
        self.btn_clear_marks.setToolTip("Удалить все метки")
        self.btn_clear_marks.clicked.connect(self.clear_marks)

        self.lbl_marks = QLabel("")
        self.lbl_marks.setStyleSheet("color: #FF9800; font-size: 11px; min-width: 24px;")

        lbl_min = QLabel("Мин дБ:")
        lbl_min.setStyleSheet(_lbl)
        self.spin_db_min = self._make_spin(-140, 0, self._DB_MIN, _spin_style)
        self.spin_db_min.valueChanged.connect(self._on_db_range_changed)

        lbl_max = QLabel("Макс дБ:")
        lbl_max.setStyleSheet(_lbl)
        self.spin_db_max = self._make_spin(-140, 0, self._DB_MAX, _spin_style)
        self.spin_db_max.valueChanged.connect(self._on_db_range_changed)

        self.lbl_fps = QLabel("—")
        self.lbl_fps.setStyleSheet("color: #444; font-size: 11px;")

        lo.addWidget(self.btn_peak)
        lo.addWidget(self.btn_reset_peak)
        lo.addSpacing(14)
        lo.addWidget(self.btn_mark)
        lo.addWidget(self.btn_clear_marks)
        lo.addWidget(self.lbl_marks)
        lo.addSpacing(14)
        lo.addWidget(lbl_min)
        lo.addWidget(self.spin_db_min)
        lo.addWidget(lbl_max)
        lo.addWidget(self.spin_db_max)
        lo.addStretch()
        lo.addWidget(self.lbl_fps)
        return bar

    @staticmethod
    def _make_spin(lo, hi, val, style) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setSingleStep(5.0)
        s.setDecimals(0)
        s.setFixedWidth(58)
        s.setStyleSheet(style)
        return s

    def _build_plot(self) -> QWidget:
        self._pw = pg.PlotWidget()
        self._pw.setBackground("#06060a")
        self._pw.setAntialiasing(True)

        pi = self._pw.getPlotItem()
        pi.setLabel("left",   "Уровень, дБ",    color="#777")
        pi.setLabel("bottom", "Частота, МГц",   color="#777")
        pi.showGrid(x=True, y=True, alpha=0.2)
        pi.setClipToView(True)
        pi.setDownsampling(auto=True, mode="peak")

        for axis_name in ("left", "bottom"):
            ax = pi.getAxis(axis_name)
            ax.setTextPen(pg.mkPen("#888"))
            ax.setPen(pg.mkPen("#333"))

        vb = pi.getViewBox()
        vb.setMouseMode(pg.ViewBox.PanMode)
        vb.setYRange(self._DB_MIN, self._DB_MAX, padding=0.05)
        vb.disableAutoRange(axis=pg.ViewBox.YAxis)

        # Живой спектр — неоновый зелёный с полупрозрачной заливкой (gqrx-стиль)
        self._live_curve = pi.plot(
            [], [],
            pen=pg.mkPen("#39FF14", width=1.5),
            name="Live",
            fillLevel=-300,
            fillBrush=pg.mkBrush(57, 255, 20, 22),
        )
        # Peak Hold — оранжевый пунктир
        self._peak_curve = pi.plot(
            [], [],
            pen=pg.mkPen("#FF8C00", width=1, style=Qt.PenStyle.DashLine),
            name="Peak Hold",
        )
        self._peak_curve.setVisible(self._show_peak)

        legend = pi.addLegend(offset=(10, 5))
        if legend:
            legend.setBrush(pg.mkBrush(10, 10, 18, 220))
            legend.setLabelTextColor(pg.mkColor("#999"))

        self._pw.scene().sigMouseClicked.connect(self._on_plot_click)

        w = QWidget()
        inner = QVBoxLayout(w)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(self._pw)
        return w

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def update_spectrum(self, freqs_hz: np.ndarray, amps_db: np.ndarray) -> None:
        freqs_mhz = freqs_hz / 1e6
        n = len(amps_db)

        self._live_curve.setData(freqs_mhz, amps_db)

        if self._peak_hold is None or len(self._peak_hold) != n:
            self._peak_hold = amps_db.copy()
        else:
            np.maximum(self._peak_hold, amps_db, out=self._peak_hold)
        if self._show_peak:
            self._peak_curve.setData(freqs_mhz, self._peak_hold)

        # X-диапазон устанавливается один раз при первом кадре, далее пользователь зумирует
        if not self._x_initialized:
            vb = self._pw.getPlotItem().getViewBox()
            vb.setXRange(float(freqs_mhz.min()), float(freqs_mhz.max()), padding=0.01)
            self._x_initialized = True

        self._frame_count += 1
        now = time.time()
        dt = now - self._last_time
        if dt >= 1.0:
            self.lbl_fps.setText(f"{self._frame_count / dt:.0f} кадр/с")
            self._frame_count = 0
            self._last_time = now

    def reset_peak(self) -> None:
        self._peak_hold = None
        self._peak_curve.setData([], [])

    def clear(self) -> None:
        self._peak_hold = None
        self._x_initialized = False
        self._live_curve.setData([], [])
        self._peak_curve.setData([], [])
        self.lbl_fps.setText("—")
        self._frame_count = 0
        self._last_time = time.time()

    def clear_marks(self) -> None:
        pi = self._pw.getPlotItem()
        for line in self._marked_lines:
            pi.removeItem(line)
        self._marked_lines.clear()
        self.marked_freqs_mhz.clear()
        self._update_mark_label()

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    def _on_peak_toggle(self, checked: bool) -> None:
        self._show_peak = checked
        self._peak_curve.setVisible(checked)
        if not checked:
            self._peak_curve.setData([], [])

    def _on_db_range_changed(self) -> None:
        lo = self.spin_db_min.value()
        hi = self.spin_db_max.value()
        if lo < hi:
            vb = self._pw.getPlotItem().getViewBox()
            vb.setYRange(lo, hi, padding=0.05)

    def _on_plot_click(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        vb = self._pw.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(event.scenePos()):
            return
        freq_mhz = float(vb.mapSceneToView(event.scenePos()).x())
        if self.btn_mark.isChecked():
            self._add_mark(freq_mhz)
        else:
            self.freq_selected.emit(freq_mhz)

    def _add_mark(self, freq_mhz: float) -> None:
        line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#FF9800", width=1.5, style=Qt.PenStyle.DashLine),
            label=f"{freq_mhz:.3f} МГц",
            labelOpts={
                "color": "#FF9800",
                "position": 0.88,
                "fill": pg.mkBrush(20, 10, 0, 190),
            },
        )
        line.setPos(freq_mhz)
        self._pw.getPlotItem().addItem(line)
        self._marked_lines.append(line)
        self.marked_freqs_mhz.append(freq_mhz)
        self._update_mark_label()
        self.freq_marked.emit(freq_mhz)

    def _update_mark_label(self) -> None:
        n = len(self.marked_freqs_mhz)
        self.lbl_marks.setText(f"📌 {n}" if n else "")
