from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt
import pyqtgraph as pg
import numpy as np

class SpectrumPlotWidget(QWidget):
    def __init__(self):
        super().__init__()
        
        # 1. Настройка виджета графика
        self.plot = pg.PlotWidget()
        self.plot.setBackground('#2b2b2b')
        
        # 2. ViewBox
        vb = self.plot.getPlotItem().getViewBox()
        vb.setMouseMode(pg.ViewBox.PanMode) # ЛКМ - перемещение, Колесо - зум
        
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        
        styles = {'color': '#ffffff', 'font-size': '12px'}
        self.plot.setLabel('left', 'Уровень, дБ', **styles)
        self.plot.setLabel('bottom', 'Частота, МГц', **styles)
        self.plot.setTitle("Панорама спектра", color='#ffffff')
        
        self.plot.setClipToView(True)
        self.plot.setDownsampling(mode='peak')
        self.plot.setAutoVisible(y=True)
        
        # Легенда
        self.legend = self.plot.addLegend(offset=(10, 10))
        if self.legend:
            self.legend.setBrush(pg.mkBrush(50, 50, 50, 200))
            try:
                self.legend.labelTextColor = (255, 255, 255)
            except AttributeError:
                pass

        # --- Панель кнопок (Правый верхний угол) ---
        self.control_panel = QWidget(self.plot)
        self.control_panel.setStyleSheet("""
            QWidget {
                background-color: rgba(40, 40, 40, 200);
                border-radius: 4px;
            }
        """)
        panel_layout = QHBoxLayout(self.control_panel)
        panel_layout.setContentsMargins(5, 5, 5, 5)
        panel_layout.setSpacing(5)

        # Кнопка Автомасштабирования
        self.btn_auto_scale = QPushButton("⟲ Авто")
        self.btn_auto_scale.setStyleSheet("""
            QPushButton {
                background-color: #555; color: white; border: none;
                padding: 4px 8px; border-radius: 3px; font-size: 11px;
            }
            QPushButton:hover { background-color: #777; }
        """)
        self.btn_auto_scale.clicked.connect(self.reset_zoom)
        
        # Кнопка Маркеров ПЭМИН
        self.btn_markers = QPushButton("👁 ПЭМИН")
        self.btn_markers.setCheckable(True)
        self.btn_markers.setStyleSheet("""
            QPushButton {
                background-color: #555; color: #aaa; border: none;
                padding: 4px 8px; border-radius: 3px; font-size: 11px;
            }
            QPushButton:checked {
                background-color: #2E7D32; color: white;
            }
            QPushButton:hover { background-color: #777; }
        """)
        self.btn_markers.toggled.connect(self._on_marker_toggle)

        panel_layout.addWidget(self.btn_auto_scale)
        panel_layout.addWidget(self.btn_markers)
        
        # Размещаем панель в правом верхнем углу (будет обновляться в resizeEvent)
        self.control_panel.move(10, 10)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)
        
        self.curves = {}
        self.threshold_line = None
        self.signal_markers = []
        self.markers_visible = False # По умолчанию скрыты

    def resizeEvent(self, event):
        """При изменении размера окна двигаем панель в правый верхний угол"""
        super().resizeEvent(event)
        panel_w = self.control_panel.width()
        margin = 10
        x = self.width() - panel_w - margin
        y = margin
        self.control_panel.move(x, y)

    def _on_marker_toggle(self, checked):
        """Обработка переключения кнопки маркеров"""
        self.markers_visible = checked
        for marker in self.signal_markers:
            marker.setVisible(checked)
        
        if checked:
            self.btn_markers.setText("🙈 Скрыть")
        else:
            self.btn_markers.setText("👁 ПЭМИН")

    def clear_markers(self):
        for marker in self.signal_markers:
            self.plot.removeItem(marker)
        self.signal_markers.clear()

    def plot_signals(self, signals):
        """Отрисовка маркеров (изначально скрыты, если кнопка не нажата)"""
        self.clear_markers()
        if not signals: return

        for sig in signals:
            freq_mhz = sig.frequency_hz / 1e6
            if sig.verified_1 is False or sig.verified_2 is False:
                color = (255, 50, 50)
            elif sig.verified_1 is True and sig.verified_2 is True:
                color = (50, 255, 50)
            else:
                color = (255, 255, 50)
            
            line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color, width=1.5, style=Qt.PenStyle.DashLine))
            line.setPos(freq_mhz)
            line.setVisible(self.markers_visible) # Применяем текущее состояние видимости
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

    def add(self, name, freqs_mhz, amps_db, color_hex, fill=None, width=1):
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
            curve = self.plot.plot(f_plot, a_plot, pen=pen, name=name, fillLevel=0, fillBrush=brush)
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
            self.threshold_line = self.plot.plot(x, y, pen=pg.mkPen('r', width=2, style=Qt.PenStyle.DashLine), name=f'Порог ({val_db} дБ)')
        else:
            self.threshold_line.setData(x, y)
            
    def reset_zoom(self):
        """Сброс масштаба: X - по всему диапазону данных, Y - авто"""
        vb = self.plot.getPlotItem().getViewBox()
        
        # Если есть данные, берем их границы для оси X
        if self.curves:
            first_curve_name = list(self.curves.keys())[0]
            curve_data = self.curves[first_curve_name]
            x_data, _ = curve_data.getData()
            if x_data is not None and len(x_data) > 0:
                min_freq = np.min(x_data)
                max_freq = np.max(x_data)
                # Жестко задаем X с небольшим отступом
                vb.setXRange(min_freq, max_freq, padding=0.02)
        
        # Авто-масштаб по Y
        vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        
        # Обновляем линию порога на весь диапазон
        if self.threshold_line:
             view_range = self.plot.viewRange()[0]
             if view_range[0] is not None and view_range[1] is not None:
                 self.set_threshold(self.threshold_line.yData[0], [view_range[0], view_range[1]])