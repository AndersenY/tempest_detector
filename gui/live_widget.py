import time
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer


class LiveWidget(QWidget):
    """
    Live-спектр с Peak Hold и маркировкой частот.
    Оформление соответствует SpectrumPlotWidget.
    """

    freq_marked        = pyqtSignal(float)          # МГц, при добавлении метки
    freq_selected      = pyqtSignal(float)          # МГц, при клике вне режима меток
    marks_cleared      = pyqtSignal()               # все метки удалены пользователем
    fullscreen_toggled = pyqtSignal(bool)           # True = полный экран
    view_range_changed = pyqtSignal(float, float)   # (start_mhz, stop_mhz) после дебаунса
    stop_requested     = pyqtSignal()               # нажата кнопка ■ Стоп
    resume_requested   = pyqtSignal()               # нажата кнопка ▶ Возобновить

    # ── Пороги и параметры ────────────────────────────────────────────────
    _MIN_MARK_SPACING_MHZ    = 0.1    # дедупликация меток: ближе этого не добавляем
    _HIGHLIGHT_MATCH_MHZ     = 0.1    # совпадение при подсветке (≥ порога дедупа)
    _RETUNE_THRESHOLD_MHZ    = 0.05   # сдвиг данных, при котором считаем смену диапазона
    _SPAN_LOCK_TOLERANCE_MHZ = 0.01   # допуск восстановления зафиксированной полосы
    _RANGE_DEBOUNCE_MS       = 100    # дебаунс сигнала view_range_changed, мс
    _EMA_ALPHA               = 0.30   # коэффициент EMA-сглаживания живого спектра
    _ZOOM_FACTOR             = 0.7
    _FILL_LEVEL_DB           = -300   # уровень заливки под кривой Live
    _LABEL_MARK_POS          = 0.88   # позиция подписи метки по оси Y (0..1)
    _LABEL_HL_POS            = 0.95   # позиция подписи линии подсветки

    def __init__(self) -> None:
        super().__init__()
        self._peak_hold:      np.ndarray | None = None
        self._ema_spectrum:   np.ndarray | None = None
        self._ema_buf:        np.ndarray | None = None   # буфер для in-place EMA
        self._show_peak     = True
        self._mark_mode     = False
        self._x_initialized = False
        self._last_time     = time.perf_counter()
        self._frame_count   = 0
        self._marked_lines: list = []
        self.marked_freqs_mhz: list[float] = []
        self._highlight_line: pg.InfiniteLine | None = None
        self._highlight_enabled = True
        self._last_highlight_mhz: float | None = None
        # Follow-режим: ретюнинг при пане/зуме
        self._follow_span_mhz: float | None = None
        self._locked_span_mhz: float | None = None
        self._span_enforcing = False
        self._pending_range: tuple | None = None
        self._range_timer = QTimer()
        self._last_data_min = 0.0
        self._last_data_max = 0.0
        self._snap_in_progress = False
        self._range_timer.setSingleShot(True)
        self._range_timer.timeout.connect(self._emit_pending_range)
        self._setup_ui()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._build_plot_widget()
        self._build_control_panel()
        self._build_zoom_panel()
        layout.addWidget(self._pw)

    @staticmethod
    def _make_button_style(checked_bg: str | None = None) -> str:
        color = "#aaa" if checked_bg else "white"
        style = (
            f"QPushButton {{ background-color: #555; color: {color}; border: none;"
            f" padding: 4px 8px; border-radius: 3px; font-size: 11px; }}"
            f" QPushButton:hover {{ background-color: #777; }}"
        )
        if checked_bg:
            style += f" QPushButton:checked {{ background-color: {checked_bg}; color: white; }}"
        return style

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
        vb.sigXRangeChanged.connect(self._on_x_range_changed)

        self.legend = pi.addLegend(offset=(10, 10))
        if self.legend:
            self.legend.setBrush(pg.mkBrush(50, 50, 50, 200))

        self._live_curve = pi.plot(
            [], [],
            pen=pg.mkPen("#39FF14", width=1.5),
            name="Live",
            fillLevel=self._FILL_LEVEL_DB,
            fillBrush=pg.mkBrush(57, 255, 20, 22),
        )
        self._peak_curve = pi.plot(
            [], [],
            pen=pg.mkPen("#FF8C00", width=1, style=Qt.PenStyle.DashLine),
            name="Peak Hold",
        )
        self._peak_curve.setVisible(self._show_peak)

        self._pw.scene().sigMouseClicked.connect(self._on_plot_click)

    def _build_control_panel(self) -> None:
        self.control_panel = QWidget(self._pw)
        self.control_panel.setStyleSheet(
            "QWidget { background-color: rgba(40, 40, 40, 200); border-radius: 4px; }"
        )
        cp = QHBoxLayout(self.control_panel)
        cp.setContentsMargins(5, 5, 5, 5)
        cp.setSpacing(5)

        self.btn_auto_scale = QPushButton("⟲ Сброс")
        self.btn_auto_scale.setStyleSheet(self._make_button_style())
        self.btn_auto_scale.setToolTip("Сбросить масштаб")
        self.btn_auto_scale.clicked.connect(self.reset_view)

        self.btn_peak = QPushButton("Peak Hold")
        self.btn_peak.setCheckable(True)
        self.btn_peak.setChecked(True)
        self.btn_peak.setStyleSheet(self._make_button_style("#2E7D32"))
        self.btn_peak.toggled.connect(self._on_peak_toggle)

        self.btn_reset_peak = QPushButton("⟲ Peak")
        self.btn_reset_peak.setStyleSheet(self._make_button_style())
        self.btn_reset_peak.clicked.connect(self.clear_peak)

        self.btn_mark = QPushButton("📌 Метка")
        self.btn_mark.setCheckable(True)
        self.btn_mark.setStyleSheet(self._make_button_style("#E65100"))
        self.btn_mark.setToolTip("Режим меток: кликните на спектр для отметки частоты")

        self.btn_clear_marks = QPushButton("✕ Метки")
        self.btn_clear_marks.setStyleSheet(self._make_button_style())
        self.btn_clear_marks.setToolTip("Удалить все метки")
        self.btn_clear_marks.clicked.connect(self._on_clear_marks_clicked)

        self.lbl_fps = QLabel("—")
        self.lbl_fps.setStyleSheet("color: #666; font-size: 11px; min-width: 45px;")

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setCheckable(True)
        self.btn_fullscreen.setFixedSize(28, 28)
        self.btn_fullscreen.setToolTip("На весь экран / Свернуть")
        self.btn_fullscreen.setStyleSheet(self._make_button_style("#2E7D32").replace(
            "padding: 4px 8px", "padding: 2px"
        ) + " font-size: 14px;")
        self.btn_fullscreen.toggled.connect(self.fullscreen_toggled)

        self.btn_stop_live = QPushButton("■")
        self.btn_stop_live.setFixedSize(28, 28)
        self.btn_stop_live.setToolTip("Остановить прямой эфир")
        self.btn_stop_live.setStyleSheet(
            "QPushButton { background-color: #C62828; color: white; border: none;"
            " padding: 2px; border-radius: 3px; font-size: 12px; }"
            " QPushButton:hover { background-color: #B71C1C; }"
        )
        self.btn_stop_live.clicked.connect(self.stop_requested)

        self.btn_resume_live = QPushButton("▶")
        self.btn_resume_live.setFixedSize(28, 28)
        self.btn_resume_live.setToolTip("Возобновить прямой эфир")
        self.btn_resume_live.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; border: none;"
            " padding: 2px; border-radius: 3px; font-size: 12px; }"
            " QPushButton:hover { background-color: #1B5E20; }"
        )
        self.btn_resume_live.clicked.connect(self.resume_requested)
        self.btn_resume_live.setVisible(False)

        for w in (self.btn_auto_scale, self.btn_peak, self.btn_reset_peak,
                  self.btn_mark, self.btn_clear_marks, self.lbl_fps,
                  self.btn_fullscreen, self.btn_stop_live, self.btn_resume_live):
            cp.addWidget(w)

    def _build_zoom_panel(self) -> None:
        self.zoom_panel = QWidget(self._pw)
        self.zoom_panel.setStyleSheet(
            "QWidget { background-color: rgba(40, 40, 40, 200); border-radius: 4px; }"
        )
        zp = QHBoxLayout(self.zoom_panel)
        zp.setContentsMargins(5, 5, 5, 5)
        zp.setSpacing(8)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedSize(28, 28)
        self.btn_zoom_in.setStyleSheet(self._make_button_style())
        self.btn_zoom_in.clicked.connect(self._zoom_in)

        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setFixedSize(28, 28)
        self.btn_zoom_out.setStyleSheet(self._make_button_style())
        self.btn_zoom_out.clicked.connect(self._zoom_out)

        zp.addWidget(self.btn_zoom_in)
        zp.addWidget(self.btn_zoom_out)

    def _reposition_panels(self) -> None:
        self.control_panel.adjustSize()
        pw = self.control_panel.width()
        self.control_panel.move(self.width() - pw - 10, 10)
        self.zoom_panel.adjustSize()
        zw = self.zoom_panel.width()
        zh = self.zoom_panel.height()
        self.zoom_panel.move(self.width() - zw - 40, self.height() - zh - 60)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_panels()

    def closeEvent(self, event) -> None:
        self._range_timer.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def update_spectrum(self, freqs_hz: np.ndarray, amps_db: np.ndarray) -> None:
        if len(amps_db) == 0:
            return

        freqs_mhz = freqs_hz / 1e6
        n = len(amps_db)
        data_min = float(freqs_mhz.min())
        data_max = float(freqs_mhz.max())

        range_shifted = (
            abs(data_min - self._last_data_min) > self._RETUNE_THRESHOLD_MHZ or
            abs(data_max - self._last_data_max) > self._RETUNE_THRESHOLD_MHZ
        )

        # EMA-сглаживание; при смене диапазона — сброс для чистого старта
        if self._ema_spectrum is None or len(self._ema_spectrum) != n or range_shifted:
            self._ema_spectrum = amps_db.copy()
            self._ema_buf = np.empty(n, dtype=self._ema_spectrum.dtype)
        else:
            # in-place: ema += alpha * (amps - ema) без временных массивов
            np.subtract(amps_db, self._ema_spectrum, out=self._ema_buf)
            np.multiply(self._ema_buf, self._EMA_ALPHA, out=self._ema_buf)
            np.add(self._ema_spectrum, self._ema_buf, out=self._ema_spectrum)
        self._live_curve.setData(freqs_mhz, self._ema_spectrum)

        # Peak Hold; при смене диапазона сбрасываем — старые данные к новым частотам не относятся
        if self._peak_hold is None or len(self._peak_hold) != n or range_shifted:
            self._peak_hold = amps_db.copy()
        else:
            np.maximum(self._peak_hold, amps_db, out=self._peak_hold)
        if self._show_peak:
            self._peak_curve.setData(freqs_mhz, self._peak_hold)

        if not self._x_initialized or (self._follow_span_mhz is not None and range_shifted):
            vb = self._pw.getPlotItem().getViewBox()
            self._snap_in_progress = True
            vb.setXRange(data_min, data_max, padding=0)
            y_center = float(np.mean(amps_db))
            y_span   = max(float(amps_db.max() - amps_db.min()) * 1.4, 40.0)
            vb.setYRange(y_center - y_span / 2, y_center + y_span / 2, padding=0)
            self._snap_in_progress = False
            self._x_initialized = True
        self._last_data_min = data_min
        self._last_data_max = data_max

        self._frame_count += 1
        now = time.perf_counter()
        dt = now - self._last_time
        if dt >= 1.0:
            self.lbl_fps.setText(f"{self._frame_count / dt:.0f} к/с")
            self._frame_count = 0
            self._last_time = now

    def clear_peak(self) -> None:
        self._peak_hold = None
        self._peak_curve.setData([], [])

    def reset_view(self) -> None:
        """Сбросить масштаб: X по текущим данным, Y — по видимым кривым."""
        vb = self._pw.getPlotItem().getViewBox()
        data = self._live_curve.getData()
        if data[0] is not None and len(data[0]) > 0:
            vb.setXRange(float(data[0].min()), float(data[0].max()), padding=0.01)

        curves = [self._live_curve]
        if self._show_peak:
            curves.append(self._peak_curve)

        all_y_arrays = []
        for curve in curves:
            yd = curve.getData()[1]
            if yd is not None and len(yd) > 0:
                all_y_arrays.append(yd)
        if all_y_arrays:
            combined = np.concatenate(all_y_arrays)
            y_center = float(np.mean(combined))
            y_span   = max(float(combined.max() - combined.min()) * 1.4, 40.0)
            vb.setYRange(y_center - y_span / 2, y_center + y_span / 2, padding=0)
        else:
            vb.enableAutoRange(axis=pg.ViewBox.YAxis)

    def clear(self) -> None:
        pi = self._pw.getPlotItem()
        if self._highlight_line is not None:
            pi.removeItem(self._highlight_line)
            self._highlight_line = None
        self._peak_hold    = None
        self._ema_spectrum = None
        self._ema_buf      = None
        self._x_initialized = False
        self._last_data_min = 0.0
        self._last_data_max = 0.0
        self._last_highlight_mhz = None
        self._live_curve.setData([], [])
        self._peak_curve.setData([], [])
        self.lbl_fps.setText("—")
        self._frame_count = 0
        self._last_time = time.perf_counter()

    def clear_marks(self) -> None:
        pi = self._pw.getPlotItem()
        for line in self._marked_lines:
            pi.removeItem(line)
        self._marked_lines.clear()
        self.marked_freqs_mhz.clear()

    def set_marks(self, freqs_mhz: list[float]) -> None:
        """Синхронизировать метки с внешним списком. Сигнал freq_marked не испускается."""
        self.clear_marks()
        pi = self._pw.getPlotItem()
        for f in freqs_mhz:
            if not isinstance(f, (int, float)):
                continue
            if any(abs(existing - f) < self._MIN_MARK_SPACING_MHZ
                   for existing in self.marked_freqs_mhz):
                continue
            line = self._make_mark_line(f)
            line.setPos(f)
            pi.addItem(line)
            self._marked_lines.append(line)
            self.marked_freqs_mhz.append(float(f))

    def highlight_mark(self, freq_mhz: float | None) -> None:
        """Подсветить выбранную частоту белой линией. Передать None для сброса."""
        self._last_highlight_mhz = freq_mhz

        for line, f in zip(self._marked_lines, self.marked_freqs_mhz):
            is_sel = freq_mhz is not None and abs(f - freq_mhz) < self._HIGHLIGHT_MATCH_MHZ
            color  = "#FFFFFF" if is_sel else "#FF9800"
            width  = 2.5      if is_sel else 1.5
            line.setPen(pg.mkPen(color, width=width, style=Qt.PenStyle.DashLine))

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
                    "position": self._LABEL_HL_POS,
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
        elif not checked and self._highlight_line is not None:
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
                "position": self._LABEL_MARK_POS,
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
            return
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

    # ------------------------------------------------------------------
    # Follow-режим: фиксированная полоса, ретюнинг при пане
    # ------------------------------------------------------------------

    def set_live_running(self, running: bool) -> None:
        """Переключить вид кнопок ■/▶ в зависимости от состояния потока."""
        self.btn_stop_live.setVisible(running)
        self.btn_resume_live.setVisible(not running)
        self._reposition_panels()

    def set_follow_mode(self, span_mhz: float | None) -> None:
        """Включить/выключить follow-режим. span_mhz=None — выключить."""
        self._follow_span_mhz = span_mhz

    def set_span_lock(self, span_mhz: float | None) -> None:
        """Зафиксировать ширину полосы (только пан, зум запрещён). None — снять."""
        self._locked_span_mhz = span_mhz
        locked = span_mhz is not None
        self.btn_zoom_in.setEnabled(not locked)
        self.btn_zoom_out.setEnabled(not locked)
        tip = "Масштабирование недоступно при зафиксированной полосе SDR" if locked else ""
        self.btn_zoom_in.setToolTip(tip)
        self.btn_zoom_out.setToolTip(tip)

    def _on_x_range_changed(self, vb, range_) -> None:
        if self._follow_span_mhz is None or not self._x_initialized or self._snap_in_progress:
            return
        x0, x1 = float(range_[0]), float(range_[1])

        if (self._locked_span_mhz is not None and
                abs((x1 - x0) - self._locked_span_mhz) > self._SPAN_LOCK_TOLERANCE_MHZ):
            cx = (x0 + x1) / 2
            half = self._locked_span_mhz / 2
            x0, x1 = cx - half, cx + half
            self._snap_in_progress = True
            vb.setXRange(x0, x1, padding=0)
            self._snap_in_progress = False

        self._pending_range = (x0, x1)
        self._range_timer.start(self._RANGE_DEBOUNCE_MS)

    def _emit_pending_range(self) -> None:
        if self._pending_range is not None and self._x_initialized:
            self.view_range_changed.emit(*self._pending_range)
            self._pending_range = None
