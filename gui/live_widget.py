import time
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel)
from PyQt6.QtCore import Qt, pyqtSignal


class LiveWidget(QWidget):
    """
    Live-спектр с Peak Hold и маркировкой частот.
    Оформление соответствует SpectrumPlotWidget.
    """

    freq_marked        = pyqtSignal(float)   # МГц, при добавлении метки
    freq_selected      = pyqtSignal(float)  # МГц, при клике вне режима меток
    marks_cleared      = pyqtSignal()       # все метки удалены пользователем
    fullscreen_toggled = pyqtSignal(bool)   # True = полный экран

    _MIN_MARK_SPACING_MHZ = 0.1   # 100 кГц — совпадает с порогом дедупликации закладок
    _EMA_ALPHA   = 0.35    # коэффициент EMA-сглаживания живого спектра
    _ZOOM_FACTOR = 0.7

    def __init__(self) -> None:
        super().__init__()
        self._peak_hold:      np.ndarray | None = None
        self._ema_spectrum:   np.ndarray | None = None
        self._show_peak     = True
        self._mark_mode     = False
        self._x_initialized = False
        self._last_time     = time.time()
        self._frame_count   = 0
        self._marked_lines: list = []
        self.marked_freqs_mhz: list[float] = []
        self._highlight_line: pg.InfiniteLine | None = None
        self._highlight_enabled = True
        self._last_highlight_mhz: float | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._build_plot_widget()
        layout.addWidget(self._pw)

    def _build_plot_widget(self) -> None:
        self._pw = pg.PlotWidget()
        self._pw.setBackground("#2b2b2b")
        self._pw.setAntialiasing(True)

        pi = self._pw.getPlotItem()
        pi.setLabel("left",   "Уровень, дБ",  color="#ffffff", size="12px")
        pi.setLabel("bottom", "Частота, МГц", color="#ffffff", size="12px")
        pi.setTitle("Прямой эфир", color="#ffffff")
        pi.showGrid(x=True, y=True, alpha=0.2)
        pi.setClipToView(True)
        pi.setDownsampling(auto=True, mode="peak")

        for name in ("left", "bottom"):
            ax = pi.getAxis(name)
            ax.setTextPen(pg.mkPen("#ffffff"))
            ax.setPen(pg.mkPen("#555"))

        vb = pi.getViewBox()
        vb.setMouseMode(pg.ViewBox.PanMode)

        self.legend = pi.addLegend(offset=(10, 10))
        if self.legend:
            self.legend.setBrush(pg.mkBrush(50, 50, 50, 200))

        self._live_curve = pi.plot(
            [], [],
            pen=pg.mkPen("#39FF14", width=1.5),
            name="Live",
            fillLevel=-300,
            fillBrush=pg.mkBrush(57, 255, 20, 22),
        )
        self._peak_curve = pi.plot(
            [], [],
            pen=pg.mkPen("#FF8C00", width=1, style=Qt.PenStyle.DashLine),
            name="Peak Hold",
        )
        self._peak_curve.setVisible(self._show_peak)

        self._pw.scene().sigMouseClicked.connect(self._on_plot_click)

        _btn = """
            QPushButton { background-color: #555; color: white; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:hover { background-color: #777; }
        """
        _btn_check = """
            QPushButton { background-color: #555; color: #aaa; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:checked { background-color: #E65100; color: white; }
            QPushButton:hover { background-color: #777; }
        """
        _btn_peak_style = """
            QPushButton { background-color: #555; color: #aaa; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:checked { background-color: #2E7D32; color: white; }
            QPushButton:hover { background-color: #777; }
        """

        # ── Панель управления (верхний правый угол) ────────────────────
        self.control_panel = QWidget(self._pw)
        self.control_panel.setStyleSheet(
            "QWidget { background-color: rgba(40, 40, 40, 200); border-radius: 4px; }"
        )
        cp = QHBoxLayout(self.control_panel)
        cp.setContentsMargins(5, 5, 5, 5)
        cp.setSpacing(5)

        self.btn_auto_scale = QPushButton("⟲ Сброс")
        self.btn_auto_scale.setStyleSheet(_btn)
        self.btn_auto_scale.setToolTip("Сбросить масштаб")
        self.btn_auto_scale.clicked.connect(self.reset_view)

        self.btn_peak = QPushButton("Peak Hold")
        self.btn_peak.setCheckable(True)
        self.btn_peak.setChecked(True)
        self.btn_peak.setStyleSheet(_btn_peak_style)
        self.btn_peak.toggled.connect(self._on_peak_toggle)

        self.btn_reset_peak = QPushButton("⟲ Peak")
        self.btn_reset_peak.setStyleSheet(_btn)
        self.btn_reset_peak.clicked.connect(self.reset_peak)

        self.btn_mark = QPushButton("📌 Метка")
        self.btn_mark.setCheckable(True)
        self.btn_mark.setStyleSheet(_btn_check)
        self.btn_mark.setToolTip("Режим меток: кликните на спектр для отметки частоты")

        self.btn_clear_marks = QPushButton("✕ Метки")
        self.btn_clear_marks.setStyleSheet(_btn)
        self.btn_clear_marks.setToolTip("Удалить все метки")
        self.btn_clear_marks.clicked.connect(self._on_clear_marks_clicked)

        self.lbl_fps = QLabel("—")
        self.lbl_fps.setStyleSheet("color: #666; font-size: 11px; min-width: 45px;")

        # self.btn_highlight = QPushButton("⊙ Маркер")
        # self.btn_highlight.setCheckable(True)
        # self.btn_highlight.setChecked(True)
        # self.btn_highlight.setToolTip("Показывать/скрывать выделение выбранной частоты")
        # self.btn_highlight.setStyleSheet("""
        #     QPushButton { background-color: #555; color: #aaa; border: none;
        #                   padding: 4px 8px; border-radius: 3px; font-size: 11px; }
        #     QPushButton:checked { background-color: #1565C0; color: white; }
        #     QPushButton:hover { background-color: #777; }
        # """)
        # self.btn_highlight.toggled.connect(self._on_highlight_toggle)

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setCheckable(True)
        self.btn_fullscreen.setFixedSize(28, 28)
        self.btn_fullscreen.setToolTip("На весь экран / Свернуть")
        self.btn_fullscreen.setStyleSheet("""
            QPushButton { background-color: #555; color: #ccc; border: none;
                          padding: 2px; border-radius: 3px; font-size: 14px; }
            QPushButton:checked { background-color: #1A237E; color: white; }
            QPushButton:hover { background-color: #777; }
        """)
        self.btn_fullscreen.toggled.connect(self.fullscreen_toggled)

        for w in (self.btn_auto_scale, self.btn_peak, self.btn_reset_peak,
                  self.btn_mark, self.btn_clear_marks, self.lbl_fps,
                  self.btn_fullscreen):
            cp.addWidget(w)

        # ── Кнопки масштабирования (нижний правый угол) ───────────────
        self.zoom_panel = QWidget(self._pw)
        self.zoom_panel.setStyleSheet(
            "QWidget { background-color: rgba(40, 40, 40, 200); border-radius: 4px; }"
        )
        zp = QHBoxLayout(self.zoom_panel)
        zp.setContentsMargins(5, 5, 5, 5)
        zp.setSpacing(8)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedSize(28, 28)
        self.btn_zoom_in.setStyleSheet(_btn)
        self.btn_zoom_in.clicked.connect(self._zoom_in)

        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setFixedSize(28, 28)
        self.btn_zoom_out.setStyleSheet(_btn)
        self.btn_zoom_out.clicked.connect(self._zoom_out)

        zp.addWidget(self.btn_zoom_in)
        zp.addWidget(self.btn_zoom_out)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.control_panel.adjustSize()
        pw = self.control_panel.width()
        self.control_panel.move(self.width() - pw - 10, 10)
        self.zoom_panel.adjustSize()
        zw = self.zoom_panel.width()
        zh = self.zoom_panel.height()
        self.zoom_panel.move(self.width() - zw - 40, self.height() - zh - 60)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def update_spectrum(self, freqs_hz: np.ndarray, amps_db: np.ndarray) -> None:
        freqs_mhz = freqs_hz / 1e6
        n = len(amps_db)

        # EMA-сглаживание убирает дёрганье при переходах полос SDR
        if self._ema_spectrum is None or len(self._ema_spectrum) != n:
            self._ema_spectrum = amps_db.copy()
        else:
            self._ema_spectrum += self._EMA_ALPHA * (amps_db - self._ema_spectrum)
        self._live_curve.setData(freqs_mhz, self._ema_spectrum)

        # Peak Hold по сырым данным
        if self._peak_hold is None or len(self._peak_hold) != n:
            self._peak_hold = amps_db.copy()
        else:
            np.maximum(self._peak_hold, amps_db, out=self._peak_hold)
        if self._show_peak:
            self._peak_curve.setData(freqs_mhz, self._peak_hold)

        if not self._x_initialized:
            vb = self._pw.getPlotItem().getViewBox()
            vb.setXRange(float(freqs_mhz.min()), float(freqs_mhz.max()), padding=0.01)
            self._x_initialized = True

        self._frame_count += 1
        now = time.time()
        dt = now - self._last_time
        if dt >= 1.0:
            self.lbl_fps.setText(f"{self._frame_count / dt:.0f} к/с")
            self._frame_count = 0
            self._last_time = now

    def reset_peak(self) -> None:
        self._peak_hold = None
        self._peak_curve.setData([], [])

    def reset_view(self) -> None:
        """Сбросить масштаб: X по текущим данным, Y — центр в 0 дБ."""
        vb = self._pw.getPlotItem().getViewBox()
        data = self._live_curve.getData()
        if data[0] is not None and len(data[0]) > 0:
            vb.setXRange(float(data[0].min()), float(data[0].max()), padding=0.01)

        all_y = []
        for curve in (self._live_curve, self._peak_curve):
            yd = curve.getData()[1]
            if yd is not None and len(yd) > 0:
                all_y.append(float(yd.min()))
                all_y.append(float(yd.max()))
        if all_y:
            half_span = max(abs(min(all_y)), abs(max(all_y))) * 1.1
            vb.setYRange(-half_span, half_span, padding=0)
        else:
            vb.enableAutoRange(axis=pg.ViewBox.YAxis)

    def clear(self) -> None:
        self._peak_hold    = None
        self._ema_spectrum = None
        self._x_initialized = False
        self._last_highlight_mhz = None
        self._highlight_line = None   # виджет пересоздаётся при следующем вызове highlight_mark
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

    def set_marks(self, freqs_mhz: list) -> None:
        """Синхронизировать метки с внешним списком. Сигнал freq_marked не испускается."""
        self.clear_marks()
        pi = self._pw.getPlotItem()
        for f in freqs_mhz:
            line = self._make_mark_line(f)
            line.setPos(f)
            pi.addItem(line)
            self._marked_lines.append(line)
            self.marked_freqs_mhz.append(f)

    def highlight_mark(self, freq_mhz) -> None:
        """Подсветить выбранную частоту белой линией. Передать None для сброса."""
        self._last_highlight_mhz = freq_mhz

        # Цвет метки-якоря (оранжевый/белый)
        for line, f in zip(self._marked_lines, self.marked_freqs_mhz):
            is_sel = freq_mhz is not None and abs(f - freq_mhz) < 0.001
            color  = "#FFFFFF" if is_sel else "#FF9800"
            width  = 2.5      if is_sel else 1.5
            line.setPen(pg.mkPen(color, width=width, style=Qt.PenStyle.DashLine))

        # Отдельная белая линия-индикатор (как в SpectrumWidget)
        if not self._highlight_enabled or freq_mhz is None:
            if self._highlight_line is not None:
                self._highlight_line.setVisible(False)
            return

        if self._highlight_line is None:
            self._highlight_line = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen((255, 255, 255), width=1.5, style=Qt.PenStyle.DashLine),
                label="{value:.3f} МГц",
                labelOpts={
                    "color": "#FFFFFF",
                    "position": 0.95,
                    "fill": pg.mkBrush(40, 40, 40, 210),
                },
            )
            self._highlight_line.setZValue(100)
            self._pw.getPlotItem().addItem(self._highlight_line)

        self._highlight_line.setPos(freq_mhz)
        self._highlight_line.setVisible(True)

    def _on_highlight_toggle(self, checked: bool) -> None:
        self._highlight_enabled = checked
        if checked and self._last_highlight_mhz is not None:
            self.highlight_mark(self._last_highlight_mhz)
        elif not checked:
            if self._highlight_line is not None:
                self._highlight_line.setVisible(False)

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    def _make_mark_line(self, freq_mhz: float, highlighted: bool = False) -> pg.InfiniteLine:
        color = "#FFFFFF" if highlighted else "#FF9800"
        width = 2.5      if highlighted else 1.5
        return pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen(color, width=width, style=Qt.PenStyle.DashLine),
            label=f"{freq_mhz:.3f} МГц",
            labelOpts={
                "color": color,
                "position": 0.88,
                "fill": pg.mkBrush(20, 10, 0, 190),
            },
        )

    def _on_clear_marks_clicked(self) -> None:
        self.clear_marks()
        self.marks_cleared.emit()

    def _on_peak_toggle(self, checked: bool) -> None:
        self._show_peak = checked
        self._peak_curve.setVisible(checked)
        if not checked:
            self._peak_curve.setData([], [])

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
        if any(abs(f - freq_mhz) < self._MIN_MARK_SPACING_MHZ 
            for f in self.marked_freqs_mhz):
            return  # silently ignore

        line = self._make_mark_line(freq_mhz)
        line.setPos(freq_mhz)
        self._pw.getPlotItem().addItem(line)
        self._marked_lines.append(line)
        self.marked_freqs_mhz.append(freq_mhz)
        self.freq_marked.emit(freq_mhz)

    def _zoom_in(self) -> None:
        vb = self._pw.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        cx = (x0 + x1) / 2
        half = (x1 - x0) / 2 * self._ZOOM_FACTOR
        vb.setXRange(cx - half, cx + half, padding=0)

    def _zoom_out(self) -> None:
        vb = self._pw.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        cx = (x0 + x1) / 2
        half = (x1 - x0) / 2 / self._ZOOM_FACTOR
        vb.setXRange(cx - half, cx + half, padding=0)
