from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt
import pyqtgraph as pg
import numpy as np
from typing import List


class SpectrumPlotWidget(QWidget):
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
        self.plot.setDownsampling(mode="peak")
        self.plot.setAutoVisible(y=True)

        self.legend = self.plot.addLegend(offset=(10, 10))
        if self.legend:
            self.legend.setBrush(pg.mkBrush(50, 50, 50, 200))
            try:
                self.legend.labelTextColor = (255, 255, 255)
            except AttributeError:
                pass

        # Панель кнопок
        self.control_panel = QWidget(self.plot)
        self.control_panel.setStyleSheet("""
            QWidget { background-color: rgba(40, 40, 40, 200); border-radius: 4px; }
        """)
        panel_layout = QHBoxLayout(self.control_panel)
        panel_layout.setContentsMargins(5, 5, 5, 5)
        panel_layout.setSpacing(5)

        self.btn_auto_scale = QPushButton("⟲ Авто")
        self.btn_auto_scale.setStyleSheet("""
            QPushButton { background-color: #555; color: white; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:hover { background-color: #777; }
        """)
        self.btn_auto_scale.clicked.connect(self.reset_zoom)

        self.btn_markers = QPushButton("👁 ПЭМИН")
        self.btn_markers.setCheckable(True)
        self.btn_markers.setChecked(True)  # маркеры видны по умолчанию
        self.btn_markers.setStyleSheet("""
            QPushButton { background-color: #555; color: #aaa; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:checked { background-color: #2E7D32; color: white; }
            QPushButton:hover { background-color: #777; }
        """)
        self.btn_markers.toggled.connect(self._on_marker_toggle)

        panel_layout.addWidget(self.btn_auto_scale)
        panel_layout.addWidget(self.btn_markers)
        self.control_panel.move(10, 10)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)

        self.curves = {}
        self.threshold_line = None
        self.signal_markers = []          # список InfiniteLine
        self.markers_visible = True       # начальное состояние — видны

    def resizeEvent(self, event):
        super().resizeEvent(event)
        panel_w = self.control_panel.width()
        self.control_panel.move(self.width() - panel_w - 10, 10)

    def _on_marker_toggle(self, checked: bool):
        self.markers_visible = checked
        for marker in self.signal_markers:
            marker.setVisible(checked)
        self.btn_markers.setText("🙈 Скрыть" if checked else "👁 ПЭМИН")

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

    def clear(self):
        self.plot.clear()
        self.curves.clear()
        self.clear_markers()
        self.threshold_line = None
        self.legend = self.plot.addLegend(offset=(10, 10))
        if self.legend:
            self.legend.setBrush(pg.mkBrush(50, 50, 50, 200))

    def add(self, name: str, freqs_mhz, amps_db, color_hex, fill=None, width=1):
        step = 4
        if len(freqs_mhz) > 2000:
            f_plot = freqs_mhz[::step]
            a_plot = amps_db[::step]
        else:
            f_plot = freqs_mhz
            a_plot = amps_db

        pen = pg.mkPen(color=color_hex, width=width)
        if name in self.curves:
            self.curves[name].setData(f_plot, a_plot)
        else:
            brush = pg.mkBrush(fill) if fill else None
            curve = self.plot.plot(f_plot, a_plot, pen=pen, name=name,
                                   fillLevel=0, fillBrush=brush)
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

    def reset_zoom(self):
        vb = self.plot.getPlotItem().getViewBox()
        if self.curves:
            first_curve = list(self.curves.values())[0]
            x_data, _ = first_curve.getData()
            if x_data is not None and len(x_data) > 0:
                vb.setXRange(np.min(x_data), np.max(x_data), padding=0.02)
        vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        if self.threshold_line:
            view_range = self.plot.viewRange()[0]
            if view_range[0] is not None and view_range[1] is not None:
                self.set_threshold(self.threshold_line.yData[0],
                                   [view_range[0], view_range[1]])


# ------------------------------------------------------------------
# Вспомогательная функция — определяет цвет маркера или None (скрыть)
# ------------------------------------------------------------------

def _marker_color(sig):
    """
    Возвращает RGB-кортеж для маркера или None, если сигнал не нужно рисовать.

    Правила:
      Ожидание (до верификации):   жёлтый  (255, 220, 50)
      ПЭМИН (green):               зелёный (50, 220, 80)
      Всё остальное:               None — не рисуем
    """
    # Ещё не верифицирован вообще → жёлтый («ожидание»)
    if sig.verified_1 is None and sig.verified_2 is None:
        return (255, 220, 50)

    # Промежуточный: В1 пройден, В2 ещё не запускался → жёлтый
    if sig.verified_1 is True and sig.verified_2 is None:
        return (255, 220, 50)

    # Финальный результат — только ПЭМИН
    if sig.status_color == "green":
        return (50, 220, 80)

    # Красный или синий — отбракован, не рисуем
    return None