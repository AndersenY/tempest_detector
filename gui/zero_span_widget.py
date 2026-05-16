import time
from collections import deque
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame
from PyQt6.QtCore import Qt, pyqtSignal
from gui.theme import DARK, btn_normal, btn_toggle, btn_icon, btn_danger


class ZeroSpanWidget(QWidget):
    """
    Осциллографический вид — амплитуда (дБ) как функция времени.
    Оформление соответствует SpectrumPlotWidget и LiveWidget:
      • тот же фон (bg_plot), сетка alpha=0.2, шрифт 12px
      • overlay-панель кнопок в правом верхнем углу
      • курсор (vline + hline + текстовая метка)
      • текущий уровень — overlay в левом верхнем углу
    """

    pause_requested    = pyqtSignal()
    resume_requested   = pyqtSignal()
    audio_toggled      = pyqtSignal(bool)
    fullscreen_toggled = pyqtSignal(bool)

    _MAX_POINTS = 300

    def __init__(self) -> None:
        super().__init__()
        self._theme   = DARK
        self._buffer: deque = deque(maxlen=self._MAX_POINTS)
        self._times:  deque = deque(maxlen=self._MAX_POINTS)
        self._t_start: float | None = None
        self._t_offset: float = 0.0          # суммарное время всех пауз
        self._last_point_mono: float | None = None  # monotonic-время последней точки
        self._resuming: bool = False         # флаг: следующая точка закрывает разрыв
        self._cursor_enabled = True
        self._setup_ui()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        t = self._theme

        # ── График ────────────────────────────────────────────────────
        self._pw = pg.PlotWidget()
        self._pw.setBackground(t["bg_plot"])
        self._pw.setAntialiasing(True)

        pi = self._pw.getPlotItem()
        pi.setLabel("left",   "Уровень, дБ", color=t["text_axis"], size="12px")
        pi.setLabel("bottom", "Время, с",    color=t["text_axis"], size="12px")
        pi.setTitle("Мониторинг частоты", color=t["text_axis"])
        pi.showGrid(x=True, y=True, alpha=0.2)

        for name in ("left", "bottom"):
            ax = pi.getAxis(name)
            ax.setTextPen(pg.mkPen(t["text_axis"]))
            ax.setPen(pg.mkPen(t["axis_pen"]))

        vb = pi.getViewBox()
        vb.setMouseMode(pg.ViewBox.PanMode)

        self._curve = pi.plot([], [], pen=pg.mkPen(t["zs_level_fg"], width=2))

        self._mean_line = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen("#FF8F00", width=1.5, style=Qt.PenStyle.DashLine),
            label="Среднее",
            labelOpts={
                "color": "#FF8F00", "position": 0.98,
                "fill": pg.mkBrush(60, 40, 0, 160),
            },
        )
        self._mean_line.setVisible(False)
        self._show_mean = True
        pi.addItem(self._mean_line)

        self._setup_cursor()
        self._pw.scene().sigMouseMoved.connect(self._on_mouse_moved)

        layout.addWidget(self._pw)

        # ── Текущий уровень — overlay левый верхний угол ──────────────
        self._lbl_current = QLabel("— дБ", self._pw)
        self._lbl_current.setStyleSheet(
            f"color: {t['zs_level_fg']}; font-size: 16px; font-weight: bold;"
            " font-family: monospace; background: transparent;"
        )

        # ── Overlay-панель кнопок — правый верхний угол ───────────────
        self.control_panel = QWidget(self._pw)
        self.control_panel.setStyleSheet(
            f"QWidget {{ background-color: {t['bg_panel']}; border-radius: 4px; }}"
        )
        cp = QHBoxLayout(self.control_panel)
        cp.setContentsMargins(5, 5, 5, 5)
        cp.setSpacing(4)

        self.btn_reset_zoom = QPushButton("⟲ Сброс")
        self.btn_reset_zoom.setToolTip("Подогнать масштаб Y по текущим данным")
        self.btn_reset_zoom.setStyleSheet(btn_normal(t))
        self.btn_reset_zoom.clicked.connect(self._reset_zoom)

        self.btn_cursor = QPushButton("⊕ Курсор")
        self.btn_cursor.setCheckable(True)
        self.btn_cursor.setChecked(True)
        self.btn_cursor.setToolTip("Показывать время и уровень при наведении мыши")
        self.btn_cursor.setStyleSheet(btn_toggle(t))
        self.btn_cursor.toggled.connect(self._on_cursor_toggle)

        self.btn_audio = QPushButton("Звук")
        self.btn_audio.setCheckable(True)
        self.btn_audio.setChecked(False)   # выключен по умолчанию
        self.btn_audio.setToolTip(
            "Включить/выключить аудиотон\n"
            "(частота тона пропорциональна уровню сигнала)"
        )
        self.btn_audio.setStyleSheet(btn_toggle(t))
        self.btn_audio.toggled.connect(self.audio_toggled)

        self.btn_mean = QPushButton("Среднее")
        self.btn_mean.setCheckable(True)
        self.btn_mean.setChecked(True)
        self.btn_mean.setToolTip("Показать/скрыть линию среднего значения")
        self.btn_mean.setStyleSheet(btn_toggle(t))
        self.btn_mean.toggled.connect(self._on_mean_toggle)

        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.VLine)
        self._sep.setFrameShadow(QFrame.Shadow.Sunken)
        self._sep.setStyleSheet(f"color: {t['sep']};")
        self._sep.setFixedWidth(1)

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setCheckable(True)
        self.btn_fullscreen.setFixedSize(28, 28)
        self.btn_fullscreen.setToolTip("На весь экран / Свернуть")
        self.btn_fullscreen.setStyleSheet(btn_icon(t, checkable=True))
        self.btn_fullscreen.toggled.connect(self.fullscreen_toggled)

        self.btn_stop = QPushButton("■")
        self.btn_stop.setFixedSize(28, 28)
        self.btn_stop.setToolTip("Заморозить — остановить захват для изучения графика")
        self.btn_stop.setStyleSheet(btn_danger(t))
        self.btn_stop.clicked.connect(self._on_stop_clicked)

        self.btn_resume = QPushButton("▶")
        self.btn_resume.setFixedSize(28, 28)
        self.btn_resume.setToolTip("Возобновить захват")
        self.btn_resume.setStyleSheet(btn_icon(t))
        self.btn_resume.clicked.connect(self._on_resume_clicked)
        self.btn_resume.setVisible(False)

        cp.addWidget(self.btn_reset_zoom)
        cp.addWidget(self.btn_cursor)
        cp.addWidget(self.btn_audio)
        cp.addWidget(self.btn_mean)
        cp.addWidget(self._sep)
        cp.addWidget(self.btn_fullscreen)
        cp.addWidget(self.btn_stop)
        cp.addWidget(self.btn_resume)

    def _on_mean_toggle(self, checked: bool) -> None:
        self._show_mean = checked
        self._mean_line.setVisible(checked and len(self._buffer) > 1)

    def _on_stop_clicked(self) -> None:
        self.btn_stop.setVisible(False)
        self.btn_resume.setVisible(True)
        self._reposition_overlays()
        self.pause_requested.emit()

    def _on_resume_clicked(self) -> None:
        self._resuming = True   # следующая add_point поглотит паузу
        self.btn_resume.setVisible(False)
        self.btn_stop.setVisible(True)
        self._reposition_overlays()
        self.resume_requested.emit()

    # ------------------------------------------------------------------
    # Курсор
    # ------------------------------------------------------------------

    def _setup_cursor(self) -> None:
        t = self._theme
        cursor_pen = pg.mkPen(t["text_muted"], width=1, style=Qt.PenStyle.DotLine)
        pi = self._pw.getPlotItem()

        self._cursor_vline = pg.InfiniteLine(angle=90, movable=False, pen=cursor_pen)
        self._cursor_hline = pg.InfiniteLine(angle=0,  movable=False, pen=cursor_pen)
        for line in (self._cursor_vline, self._cursor_hline):
            line.setZValue(150)
            line.setVisible(False)
            pi.addItem(line)

        self._cursor_label = pg.TextItem(
            text="",
            color=t["text_axis"],
            fill=pg.mkBrush(*t["marker_label_fill"]),
            border=pg.mkPen(t["border_input"]),
            anchor=(0, 1),
        )
        self._cursor_label.setZValue(200)
        self._cursor_label.setVisible(False)
        pi.addItem(self._cursor_label)

    def _on_cursor_toggle(self, checked: bool) -> None:
        self._cursor_enabled = checked
        if not checked:
            self._cursor_vline.setVisible(False)
            self._cursor_hline.setVisible(False)
            self._cursor_label.setVisible(False)

    def _on_mouse_moved(self, pos) -> None:
        if not self._cursor_enabled:
            return
        vb = self._pw.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(pos):
            self._cursor_vline.setVisible(False)
            self._cursor_hline.setVisible(False)
            self._cursor_label.setVisible(False)
            return

        pt = vb.mapSceneToView(pos)
        t_sec = pt.x()

        data = self._curve.getData()
        if data[0] is not None and len(data[0]) > 1:
            idx = int(np.searchsorted(data[0], t_sec))
            idx = max(0, min(idx, len(data[0]) - 1))
            amp_db = float(data[1][idx])
        else:
            amp_db = pt.y()

        self._cursor_vline.setPos(t_sec)
        self._cursor_hline.setPos(amp_db)
        self._cursor_vline.setVisible(True)
        self._cursor_hline.setVisible(True)

        x0, x1 = vb.viewRange()[0]
        anchor = (0, 1) if t_sec < (x0 + x1) / 2 else (1, 1)
        self._cursor_label.setAnchor(anchor)
        self._cursor_label.setPos(t_sec, amp_db)
        c = self._theme["text_axis"]
        self._cursor_label.setHtml(
            f'<span style="color:{c}; white-space:nowrap;">'
            f"&nbsp;{t_sec:.1f}&nbsp;с<br>"
            f"&nbsp;{amp_db:.1f}&nbsp;дБ&nbsp;"
            f"</span>"
        )
        self._cursor_label.setVisible(True)

    # ------------------------------------------------------------------
    # Позиционирование overlay-элементов
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_overlays()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._reposition_overlays()

    def _reposition_overlays(self) -> None:
        self._lbl_current.adjustSize()
        self._lbl_current.move(10, 10)
        self.control_panel.adjustSize()
        panel_w = self.control_panel.width()
        self.control_panel.move(self._pw.width() - panel_w - 10, 10)

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    def set_signal_info(self, freq_hz: float) -> None:
        """Установить заголовок с частотой перед стартом."""
        self._pw.getPlotItem().setTitle(
            f"Мониторинг  —  <b>{freq_hz / 1e6:.4f} МГц</b>",
            color=self._theme["text_axis"],
        )
        self._mean_line.setVisible(False)

    def set_running(self, running: bool) -> None:
        """Синхронизировать кнопки ■/▶ с состоянием воркера."""
        self.btn_stop.setVisible(running)
        self.btn_resume.setVisible(not running)
        self._reposition_overlays()

    def reset_audio_button(self) -> None:
        """Сбросить кнопку звука в выключенное состояние (без испускания сигнала)."""
        self.btn_audio.blockSignals(True)
        self.btn_audio.setChecked(False)
        self.btn_audio.blockSignals(False)

    def add_point(self, amp_db: float) -> None:
        """Добавить очередную точку (вызывается из ZeroSpanWorker через Qt-сигнал)."""
        now = time.monotonic()
        if self._t_start is None:
            self._t_start = now
        if self._resuming and self._last_point_mono is not None:
            # Поглощаем паузу: сдвигаем offset на длину простоя,
            # чтобы новая точка оказалась сразу после последней перед паузой.
            self._t_offset += now - self._last_point_mono
            self._resuming = False
        self._last_point_mono = now
        self._times.append(now - self._t_start - self._t_offset)
        self._buffer.append(amp_db)
        self._refresh(amp_db)

    def clear(self) -> None:
        self._buffer.clear()
        self._times.clear()
        self._t_start = None
        self._t_offset = 0.0
        self._last_point_mono = None
        self._resuming = False
        self._curve.setData([], [])
        self._mean_line.setVisible(False)
        self._lbl_current.setText("— дБ")
        self.reset_audio_button()

    # ------------------------------------------------------------------
    # Тема оформления
    # ------------------------------------------------------------------

    def apply_theme(self, t: dict) -> None:
        self._theme = t
        self._pw.setBackground(t["bg_plot"])
        pi = self._pw.getPlotItem()
        pi.setLabel("left",   "Уровень, дБ", color=t["text_axis"], size="12px")
        pi.setLabel("bottom", "Время, с",    color=t["text_axis"], size="12px")
        for name in ("left", "bottom"):
            ax = pi.getAxis(name)
            ax.setTextPen(pg.mkPen(t["text_axis"]))
            ax.setPen(pg.mkPen(t["axis_pen"]))
        self._curve.setPen(pg.mkPen(t["zs_level_fg"], width=2))
        self._lbl_current.setStyleSheet(
            f"color: {t['zs_level_fg']}; font-size: 16px; font-weight: bold;"
            " font-family: monospace; background: transparent;"
        )
        self.control_panel.setStyleSheet(
            f"QWidget {{ background-color: {t['bg_panel']}; border-radius: 4px; }}"
        )
        self.btn_reset_zoom.setStyleSheet(btn_normal(t))
        self.btn_cursor.setStyleSheet(btn_toggle(t))
        self.btn_audio.setStyleSheet(btn_toggle(t))
        self.btn_mean.setStyleSheet(btn_toggle(t))
        self.btn_fullscreen.setStyleSheet(btn_icon(t, checkable=True))
        self.btn_stop.setStyleSheet(btn_danger(t))
        self.btn_resume.setStyleSheet(btn_icon(t))
        self._sep.setStyleSheet(f"color: {t['sep']};")

        cursor_pen = pg.mkPen(t["text_muted"], width=1, style=Qt.PenStyle.DotLine)
        self._cursor_vline.setPen(cursor_pen)
        self._cursor_hline.setPen(cursor_pen)
        self._cursor_label.setColor(t["text_axis"])
        self._cursor_label.fill = pg.mkBrush(*t["marker_label_fill"])
        self._cursor_label.border = pg.mkPen(t["border_input"])
        self._cursor_label.update()

    # ------------------------------------------------------------------
    # Внутреннее
    # ------------------------------------------------------------------

    def _reset_zoom(self) -> None:
        """Подогнать Y-диапазон по текущим данным в буфере."""
        vb = self._pw.getPlotItem().getViewBox()
        if not self._buffer:
            vb.enableAutoRange(axis=pg.ViewBox.YAxis)
            return
        buf = np.array(self._buffer)
        if len(buf) < 2:
            return
        spread = max(buf.max() - buf.min(), 2.0)
        margin = spread * 0.2
        vb.setYRange(buf.min() - margin, buf.max() + margin, padding=0)

    def _refresh(self, current_db: float) -> None:
        t_arr = np.array(self._times)
        a_arr = np.array(self._buffer)
        self._curve.setData(t_arr, a_arr)
        self._lbl_current.setText(f"{current_db:+.1f} дБ")
        self._lbl_current.adjustSize()

        n = len(a_arr)
        if n == 1:
            # Первая точка — центрируем Y-диапазон
            vb = self._pw.getPlotItem().getViewBox()
            vb.setYRange(current_db - 15, current_db + 15, padding=0)

        if n > 1:
            # X — полный временной ряд
            self._pw.getPlotItem().getViewBox().setXRange(
                float(t_arr[0]), float(t_arr[-1]), padding=0.02
            )

        # Линия среднего
        if n >= 2 and self._show_mean:
            self._mean_line.setValue(float(np.mean(a_arr)))
            self._mean_line.setVisible(True)
        elif n < 2:
            self._mean_line.setVisible(False)
