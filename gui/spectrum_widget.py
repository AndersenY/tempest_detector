from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
import pyqtgraph as pg
import numpy as np
from typing import List


class SpectrumPlotWidget(QWidget):
    freq_clicked = pyqtSignal(float)          # МГц, клик в обычном режиме
    live_overlay_toggled = pyqtSignal(bool)   # запрос live overlay
    freq_mark_added = pyqtSignal(float)       # МГц, добавлена метка в режиме меток

    def __init__(self):
        super().__init__()

        self.plot = pg.PlotWidget()
        self.plot.setBackground("#2b2b2b")

        vb = self.plot.getPlotItem().getViewBox()
        vb.setMouseMode(pg.ViewBox.PanMode)

        self.plot.showGrid(x=True, y=True, alpha=0.2)

        styles = {"color": "#ffffff", "font-size": "12px"}
        self.plot.setLabel("left", "Уровень, дБ", **styles)
        self.plot.setLabel("bottom", "Частота, МГц", **styles)
        self.plot.setTitle("Панорама спектра", color="#ffffff")

        self.plot.setClipToView(True)
        self.plot.setDownsampling(auto=True, mode="peak")
        self.plot.setAutoVisible(y=True)
        self.plot.setAntialiasing(True)

        self.legend = self.plot.addLegend(offset=(10, 10))
        if self.legend:
            self.legend.setBrush(pg.mkBrush(50, 50, 50, 200))
            try:
                self.legend.labelTextColor = (255, 255, 255)
            except AttributeError:
                pass

        _btn_style = """
            QPushButton { background-color: #555; color: white; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:hover { background-color: #777; }
        """
        _btn_check_style = """
            QPushButton { background-color: #555; color: #aaa; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:checked { background-color: #E65100; color: white; }
            QPushButton:hover { background-color: #777; }
        """

        # Верхняя правая панель: сброс + маркеры + метка + live
        self.control_panel = QWidget(self.plot)
        self.control_panel.setStyleSheet(
            "QWidget { background-color: rgba(40, 40, 40, 200); border-radius: 4px; }"
        )
        panel_layout = QHBoxLayout(self.control_panel)
        panel_layout.setContentsMargins(5, 5, 5, 5)
        panel_layout.setSpacing(5)

        self.btn_auto_scale = QPushButton("⟲ Сброс")
        self.btn_auto_scale.setStyleSheet(_btn_style)
        self.btn_auto_scale.clicked.connect(self.reset_zoom)

        self.btn_markers = QPushButton("👁 ПЭМИН")
        self.btn_markers.setCheckable(True)
        self.btn_markers.setChecked(True)
        self.btn_markers.setStyleSheet("""
            QPushButton { background-color: #555; color: #aaa; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:checked { background-color: #2E7D32; color: white; }
            QPushButton:hover { background-color: #777; }
        """)
        self.btn_markers.toggled.connect(self._on_marker_toggle)

        self.btn_mark_mode = QPushButton("📌 Метка")
        self.btn_mark_mode.setCheckable(True)
        self.btn_mark_mode.setToolTip("Режим меток: кликните на спектр для отметки частоты")
        self.btn_mark_mode.setStyleSheet(_btn_check_style)
        self.btn_mark_mode.toggled.connect(self._on_mark_mode_toggle)

        self.btn_clear_marks = QPushButton("✕ Метки")
        self.btn_clear_marks.setToolTip("Удалить все метки")
        self.btn_clear_marks.setStyleSheet(_btn_style)
        self.btn_clear_marks.clicked.connect(self.clear_panorama_marks)

        self.btn_live_overlay = QPushButton("📡 Live")
        self.btn_live_overlay.setCheckable(True)
        self.btn_live_overlay.setEnabled(False)
        self.btn_live_overlay.setToolTip("Наложить живой спектр поверх снимка панорамы")
        self.btn_live_overlay.setStyleSheet("""
            QPushButton { background-color: #555; color: #aaa; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:checked { background-color: #00695C; color: white; }
            QPushButton:hover   { background-color: #777; }
            QPushButton:disabled { background-color: #333; color: #555; }
        """)
        self.btn_live_overlay.toggled.connect(self._on_live_overlay_toggle)

        panel_layout.addWidget(self.btn_auto_scale)
        panel_layout.addWidget(self.btn_markers)
        panel_layout.addWidget(self.btn_mark_mode)
        panel_layout.addWidget(self.btn_clear_marks)
        panel_layout.addWidget(self.btn_live_overlay)

        # Нижняя правая панель: зум + и -
        self.zoom_panel = QWidget(self.plot)
        self.zoom_panel.setStyleSheet(
            "QWidget { background-color: rgba(40, 40, 40, 200); border-radius: 4px; }"
        )
        zoom_layout = QHBoxLayout(self.zoom_panel)
        zoom_layout.setContentsMargins(5, 5, 5, 5)
        zoom_layout.setSpacing(8)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedSize(28, 28)
        self.btn_zoom_in.setStyleSheet(_btn_style)
        self.btn_zoom_in.clicked.connect(self._zoom_in)

        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setFixedSize(28, 28)
        self.btn_zoom_out.setStyleSheet(_btn_style)
        self.btn_zoom_out.clicked.connect(self._zoom_out)

        zoom_layout.addWidget(self.btn_zoom_in)
        zoom_layout.addWidget(self.btn_zoom_out)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)

        self.curves = {}
        self.threshold_line = None
        self.signal_markers = []
        self.markers_visible = True
        self._highlight_line = None
        self._freq_range_mhz = None
        self._mark_mode = False
        self._panorama_marks: list = []   # пользовательские метки частот

        self.plot.scene().sigMouseClicked.connect(self._on_scene_click)

    _ZOOM_FACTOR = 0.7   # каждый клик сжимает/растягивает диапазон на 30 %

    def _zoom_in(self):
        vb = self.plot.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        cx = (x0 + x1) / 2
        half = (x1 - x0) / 2 * self._ZOOM_FACTOR
        vb.setXRange(cx - half, cx + half, padding=0)

    def _zoom_out(self):
        vb = self.plot.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        cx = (x0 + x1) / 2
        half = (x1 - x0) / 2 / self._ZOOM_FACTOR
        vb.setXRange(cx - half, cx + half, padding=0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        panel_w = self.control_panel.width()
        self.control_panel.move(self.width() - panel_w - 10, 10)
        zoom_w = self.zoom_panel.width()
        zoom_h = self.zoom_panel.height()
        self.zoom_panel.move(self.width() - zoom_w - 40, self.height() - zoom_h - 60)

    def _on_marker_toggle(self, checked: bool):
        self.markers_visible = checked
        for marker in self.signal_markers:
            marker.setVisible(checked)
        self.btn_markers.setText("🙈 Скрыть" if checked else "👁 ПЭМИН")

    def _on_mark_mode_toggle(self, checked: bool) -> None:
        self._mark_mode = checked

    def _on_scene_click(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        vb = self.plot.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(event.scenePos()):
            return
        point = vb.mapSceneToView(event.scenePos())
        freq_mhz = point.x()

        if self._mark_mode:
            self._add_panorama_mark(freq_mhz)
        else:
            self.freq_clicked.emit(freq_mhz)

    # ------------------------------------------------------------------
    # Метки пользователя (режим меток в панораме)
    # ------------------------------------------------------------------

    def _add_panorama_mark(self, freq_mhz: float) -> None:
        line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#FF9800", width=1.5, style=Qt.PenStyle.DashLine),
            label=f"{freq_mhz:.3f} МГц",
            labelOpts={
                "color": "#FF9800",
                "position": 0.92,
                "fill": pg.mkBrush(20, 10, 0, 190),
            },
        )
        line.setPos(freq_mhz)
        self.plot.addItem(line)
        self._panorama_marks.append(line)
        self.freq_mark_added.emit(freq_mhz)

    def clear_panorama_marks(self) -> None:
        for line in self._panorama_marks:
            self.plot.removeItem(line)
        self._panorama_marks.clear()

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    def clear_markers(self):
        for marker in self.signal_markers:
            self.plot.removeItem(marker)
        self.signal_markers.clear()

    def plot_signals(self, signals):
        """
        Отрисовывает маркеры только для сигналов со статусом:
          - «Ожидание» (verified_1 is None и verified_2 is None) → жёлтый
          - «ПЭМИН»    (status_color == "green")                  → зелёный

        Все остальные статусы (красный, синий) на графике не отображаются,
        чтобы не засорять спектр отбракованными точками.
        """
        self.clear_markers()
        if not signals:
            return

        for sig in signals:
            color = _marker_color(sig)
            if color is None:
                continue  # сигнал отбракован — не рисуем

            line = pg.InfiniteLine(
                angle=90,
                movable=False,
                pen=pg.mkPen(color, width=1.5, style=Qt.PenStyle.DashLine),
            )
            line.setPos(sig.frequency_hz / 1e6)
            line.setVisible(self.markers_visible)
            self.plot.addItem(line)
            self.signal_markers.append(line)

    def set_highlight(self, freq_mhz: float):
        """Подсвечивает выбранную частоту белой вертикальной линией поверх маркеров."""
        if self._highlight_line is None:
            self._highlight_line = pg.InfiniteLine(
                angle=90,
                movable=False,
                pen=pg.mkPen((255, 255, 255), width=2.5),
            )
            self._highlight_line.setZValue(100)   # поверх всех маркеров
            self.plot.addItem(self._highlight_line)
        self._highlight_line.setPos(freq_mhz)
        self._highlight_line.setVisible(True)

    def clear_highlight(self):
        """Убирает подсветку выбранной частоты."""
        if self._highlight_line is not None:
            self._highlight_line.setVisible(False)

    def clear(self):
        self.plot.clear()
        self.curves.clear()
        self.clear_markers()
        self._panorama_marks.clear()  # ссылки уже удалены plot.clear()
        self._highlight_line = None
        self.threshold_line = None
        self.legend = self.plot.addLegend(offset=(10, 10))
        if self.legend:
            self.legend.setBrush(pg.mkBrush(50, 50, 50, 200))
        # Сброс режима меток
        self.btn_mark_mode.blockSignals(True)
        self.btn_mark_mode.setChecked(False)
        self.btn_mark_mode.blockSignals(False)
        self._mark_mode = False

    # ------------------------------------------------------------------
    # Live overlay (динамический режим поверх снимка панорамы)
    # ------------------------------------------------------------------

    def _on_live_overlay_toggle(self, checked: bool) -> None:
        self.live_overlay_toggled.emit(checked)
        if not checked:
            self._remove_live_overlay()

    def _remove_live_overlay(self) -> None:
        if "live_overlay" in self.curves:
            self.plot.removeItem(self.curves.pop("live_overlay"))

    def update_live_overlay(self, freqs_mhz: np.ndarray, amps_db: np.ndarray) -> None:
        """Обновить или создать кривую live overlay (голубой цвет)."""
        if "live_overlay" in self.curves:
            self.curves["live_overlay"].setData(freqs_mhz, amps_db)
        else:
            curve = self.plot.plot(
                freqs_mhz, amps_db,
                pen=pg.mkPen("#00E5FF", width=1),
                name="Live",
            )
            self.curves["live_overlay"] = curve

    def enable_live_overlay_btn(self, enabled: bool) -> None:
        """Активировать кнопку live overlay (только после завершения измерения)."""
        self.btn_live_overlay.setEnabled(enabled)
        if not enabled:
            self.btn_live_overlay.blockSignals(True)
            self.btn_live_overlay.setChecked(False)
            self.btn_live_overlay.blockSignals(False)
            self._remove_live_overlay()

    def add(self, name: str, freqs_mhz, amps_db, color_hex, fill=None, width=1):
        pen = pg.mkPen(color=color_hex, width=width)
        if name in self.curves:
            self.curves[name].setData(freqs_mhz, amps_db)
        else:
            kw = {}
            if fill is not None:
                kw["fillLevel"] = 0
                kw["fillBrush"] = pg.mkBrush(fill)
            curve = self.plot.plot(freqs_mhz, amps_db, pen=pen, name=name, **kw)
            self.curves[name] = curve

    def set_threshold(self, val_db, freq_range_mhz=None):
        if freq_range_mhz is None:
            view_range = self.plot.viewRange()[0]
            if view_range[0] is not None and view_range[1] is not None:
                freq_range_mhz = [view_range[0], view_range[1]]
            else:
                freq_range_mhz = [80, 100]
        x = np.array(freq_range_mhz)
        y = np.array([val_db, val_db])
        if self.threshold_line is None:
            self.threshold_line = self.plot.plot(
                x, y,
                pen=pg.mkPen("r", width=2, style=Qt.PenStyle.DashLine),
                name=f"Порог ({val_db} дБ)",
            )
        else:
            self.threshold_line.setData(x, y)

    def set_freq_range(self, x_min_mhz: float, x_max_mhz: float):
        """Запоминает диапазон частот из настроек для кнопки сброса зума."""
        self._freq_range_mhz = (x_min_mhz, x_max_mhz)

    def pan_to(self, freq_mhz: float):
        """Центрирует граф на freq_mhz, сохраняя текущий масштаб по X."""
        vb = self.plot.getPlotItem().getViewBox()
        x_range = vb.viewRange()[0]
        half_span = (x_range[1] - x_range[0]) / 2
        vb.setXRange(freq_mhz - half_span, freq_mhz + half_span, padding=0)

    def reset_zoom(self):
        """Сбрасывает X к диапазону из настроек, Y — авто по видимым данным."""
        if not self.curves or self._freq_range_mhz is None:
            return

        x_min, x_max = self._freq_range_mhz
        vb = self.plot.getPlotItem().getViewBox()
        vb.setXRange(x_min, x_max, padding=0)
        # Y-авто только по кривым спектра (без бесконечных InfiniteLine)
        self.plot.getPlotItem().autoRange(items=list(self.curves.values()))
        # После autoRange восстанавливаем X (autoRange мог его сдвинуть)
        vb.setXRange(x_min, x_max, padding=0)

        if self.threshold_line is not None and self.threshold_line.yData is not None:
            self.set_threshold(float(self.threshold_line.yData[0]), [x_min, x_max])


# ------------------------------------------------------------------
# Вспомогательная функция — определяет цвет маркера или None (скрыть)
# ------------------------------------------------------------------

def _marker_color(sig):
    """
    Возвращает RGB-кортеж для маркера или None, если сигнал не нужно рисовать.

    Ожидание (до В1):         жёлтый
    В1 пройдена, В2 ещё нет:  жёлтый
    В1 + В2 пройдены (ПЭМИН): зелёный
    Всё остальное:             None — не рисуем
    """
    v1 = sig.verified_1
    v2 = sig.verified_2

    if v1 is None:
        return (255, 220, 50)   # ожидание до В1

    if v1 and v2 is None:
        return (255, 220, 50)   # В1 пройдена, В2 ещё не запускалась

    if v1 and v2:
        return (50, 220, 80)    # ПЭМИН подтверждён

    return None                 # В1 или В2 провалена — не рисуем
