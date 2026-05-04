from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QFrame
from PyQt6.QtCore import Qt, pyqtSignal
import pyqtgraph as pg
import numpy as np
from gui.theme import DARK


class SpectrumPlotWidget(QWidget):

    _MIN_MARK_SPACING_MHZ = 0.1   # 100 кГц — совпадает с порогом дедупликации закладок
    freq_clicked      = pyqtSignal(float)   # МГц, клик в обычном режиме
    freq_mark_added   = pyqtSignal(float)   # МГц, добавлена метка в режиме меток
    fullscreen_toggled = pyqtSignal(bool)   # True = полный экран

    def __init__(self):
        super().__init__()
        self._theme = DARK

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
        self._apply_legend_theme(self._theme)

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
        self.btn_auto_scale.setToolTip("Сбросить масштаб на графике")
        self.btn_auto_scale.setStyleSheet(_btn_style)
        self.btn_auto_scale.clicked.connect(self.reset_zoom)

        self.btn_markers = QPushButton("👁 ПЭМИН")
        self.btn_markers.setCheckable(True)
        self.btn_markers.setChecked(True)
        self.btn_markers.setToolTip("Отобразить на графике частоты")
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

        self.btn_highlight = QPushButton("⊙ Маркер")
        self.btn_highlight.setCheckable(True)
        self.btn_highlight.setChecked(True)
        self.btn_highlight.setToolTip("Показывать/скрывать выделение выбранной частоты")
        self.btn_highlight.setStyleSheet("""
            QPushButton { background-color: #555; color: #aaa; border: none;
                          padding: 4px 8px; border-radius: 3px; font-size: 11px; }
            QPushButton:checked { background-color: #1565C0; color: white; }
            QPushButton:hover { background-color: #777; }
        """)
        self.btn_highlight.toggled.connect(self._on_highlight_toggle)

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setCheckable(True)
        self.btn_fullscreen.setFixedSize(28, 28)
        self.btn_fullscreen.setToolTip("На весь экран / Свернуть")
        self.btn_fullscreen.setStyleSheet("""
            QPushButton { background-color: #555; color: #ccc; border: none;
                          padding: 2px; border-radius: 3px; font-size: 14px; }
            QPushButton:checked { background-color: #2E7D32; color: white; }
            QPushButton:hover { background-color: #777; }
        """)
        self.btn_fullscreen.toggled.connect(self.fullscreen_toggled)

        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.VLine)
        self._sep.setFrameShadow(QFrame.Shadow.Sunken)
        self._sep.setStyleSheet("color: #555;")
        self._sep.setFixedWidth(1)

        panel_layout.addWidget(self.btn_auto_scale)
        panel_layout.addWidget(self.btn_markers)
        panel_layout.addWidget(self.btn_mark_mode)
        panel_layout.addWidget(self.btn_clear_marks)
        panel_layout.addWidget(self._sep)
        panel_layout.addWidget(self.btn_fullscreen)
        # panel_layout.addWidget(self.btn_highlight)

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
        self._highlight_enabled = True
        self._last_highlight_mhz: float | None = None
        self._freq_range_mhz = None
        self._mark_mode = False
        self._panorama_marks: list = []

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

    # ------------------------------------------------------------------
    # Тема оформления
    # ------------------------------------------------------------------

    def _apply_legend_theme(self, t: dict) -> None:
        if not self.legend:
            return
        r, g, b, a = t["legend_brush"]
        self.legend.setBrush(pg.mkBrush(r, g, b, a))
        self.legend.setPen(pg.mkPen(t["border_input"]))
        try:
            self.legend.labelTextColor = t["text_axis"]
        except AttributeError:
            pass
        try:
            for _sample, label in self.legend.items:
                label.setColor(t["text_axis"])
        except Exception:
            pass

    def apply_theme(self, t: dict) -> None:
        self._theme = t
        self.plot.setBackground(t["bg_plot"])
        pi = self.plot.getPlotItem()
        s = {"color": t["text_axis"], "font-size": "12px"}
        pi.setLabel("left",   "Уровень, дБ",  **s)
        pi.setLabel("bottom", "Частота, МГц", **s)
        pi.setTitle("Панорама спектра", color=t["text_axis"])
        for name in ("left", "bottom"):
            ax = pi.getAxis(name)
            ax.setTextPen(pg.mkPen(t["text_axis"]))
            ax.setPen(pg.mkPen(t["axis_pen"]))
        self._apply_legend_theme(t)

        btn = (
            f"QPushButton {{ background-color: {t['btn_bg']}; color: {t['btn_fg']}; border: none;"
            f" padding: 4px 8px; border-radius: 3px; font-size: 11px; }}"
            f" QPushButton:hover {{ background-color: {t['btn_hover']}; }}"
        )
        self.control_panel.setStyleSheet(
            f"QWidget {{ background-color: {t['bg_panel']}; border-radius: 4px; }}"
        )
        self.btn_auto_scale.setStyleSheet(btn)
        self.btn_markers.setStyleSheet(
            f"QPushButton {{ background-color: {t['btn_bg']}; color: {t['btn_fg_off']}; border: none;"
            f" padding: 4px 8px; border-radius: 3px; font-size: 11px; }}"
            f" QPushButton:checked {{ background-color: #2E7D32; color: white; }}"
            f" QPushButton:hover {{ background-color: {t['btn_hover']}; }}"
        )
        self.btn_mark_mode.setStyleSheet(
            f"QPushButton {{ background-color: {t['btn_bg']}; color: {t['btn_fg_off']}; border: none;"
            f" padding: 4px 8px; border-radius: 3px; font-size: 11px; }}"
            f" QPushButton:checked {{ background-color: #E65100; color: white; }}"
            f" QPushButton:hover {{ background-color: {t['btn_hover']}; }}"
        )
        self.btn_clear_marks.setStyleSheet(btn)
        self.btn_fullscreen.setStyleSheet(
            f"QPushButton {{ background-color: {t['btn_bg']}; color: {t['text_dim']}; border: none;"
            f" padding: 2px; border-radius: 3px; font-size: 14px; }}"
            f" QPushButton:checked {{ background-color: #2E7D32; color: white; }}"
            f" QPushButton:hover {{ background-color: {t['btn_hover']}; }}"
        )
        self._sep.setStyleSheet(f"color: {t['sep']};")
        self.zoom_panel.setStyleSheet(
            f"QWidget {{ background-color: {t['bg_panel']}; border-radius: 4px; }}"
        )
        self.btn_zoom_in.setStyleSheet(btn)
        self.btn_zoom_out.setStyleSheet(btn)

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
        
        if any(abs(line.value() - freq_mhz) < self._MIN_MARK_SPACING_MHZ
               for line in self._panorama_marks):
            return  # silently ignore
        
        line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#FF9800", width=1.5, style=Qt.PenStyle.DashLine),
            # label=f"{freq_mhz:.3f} МГц",
            # labelOpts={
            #     "color": "#FF9800",
            #     "position": 0.92,
            #     "fill": pg.mkBrush(20, 10, 0, 190),
            # },
        )
        line.setPos(freq_mhz)
        self.plot.addItem(line)
        self._panorama_marks.append(line)
        self.freq_mark_added.emit(freq_mhz)

    def clear_panorama_marks(self) -> None:
        for line in self._panorama_marks:
            self.plot.removeItem(line)
        self._panorama_marks.clear()

    def remove_panorama_mark(self, freq_mhz: float) -> None:
        """Удалить одну метку по частоте (допуск 10 кГц)."""
        for line in list(self._panorama_marks):
            if abs(line.value() - freq_mhz) < 0.01:
                self.plot.removeItem(line)
                self._panorama_marks.remove(line)
                break

    def set_panorama_marks(self, freqs_mhz: list) -> None:
        """Пересоздать все метки из списка частот."""
        self.clear_panorama_marks()
        for f in freqs_mhz:
            self._add_panorama_mark(f)

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
        """Показывает пунктирный маркер с подписью частоты (напр. '97.000 МГц')."""
        self._last_highlight_mhz = freq_mhz
        if not self._highlight_enabled:
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
            self.plot.addItem(self._highlight_line)
        self._highlight_line.setPos(freq_mhz)
        self._highlight_line.setVisible(True)

    def clear_highlight(self):
        """Убирает маркер выбранной частоты."""
        self._last_highlight_mhz = None
        if self._highlight_line is not None:
            self._highlight_line.setVisible(False)

    def _on_highlight_toggle(self, checked: bool) -> None:
        self._highlight_enabled = checked
        if checked and self._last_highlight_mhz is not None:
            self.set_highlight(self._last_highlight_mhz)
        elif not checked and self._highlight_line is not None:
            self._highlight_line.setVisible(False)

    def clear(self):
        self.plot.clear()
        self.curves.clear()
        self.clear_markers()
        self._panorama_marks.clear()  # ссылки уже удалены plot.clear()
        self._highlight_line = None
        self.threshold_line = None
        self.legend = self.plot.addLegend(offset=(10, 10))
        self._apply_legend_theme(self._theme)
        # Сброс режима меток
        self.btn_mark_mode.blockSignals(True)
        self.btn_mark_mode.setChecked(False)
        self.btn_mark_mode.blockSignals(False)
        self._mark_mode = False

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
        """Сбрасывает X к диапазону из настроек, Y — центр в 0 дБ."""
        if not self.curves or self._freq_range_mhz is None:
            return

        x_min, x_max = self._freq_range_mhz
        vb = self.plot.getPlotItem().getViewBox()
        vb.setXRange(x_min, x_max, padding=0)

        all_y = []
        for curve in self.curves.values():
            yd = curve.getData()[1]
            if yd is not None and len(yd) > 0:
                all_y.append(float(yd.min()))
                all_y.append(float(yd.max()))
        if all_y:
            half_span = max(abs(min(all_y)), abs(max(all_y))) * 1.1
            vb.setYRange(-half_span, half_span, padding=0)

        vb.setXRange(x_min, x_max, padding=0)

        if self.threshold_line is not None and self.threshold_line.yData is not None:
            self.set_threshold(float(self.threshold_line.yData[0]), [x_min, x_max])


# ------------------------------------------------------------------
# Вспомогательная функция — определяет цвет маркера или None (скрыть)
# ------------------------------------------------------------------

def _marker_color(sig):
    """
    Возвращает RGB-кортеж для маркера или None, если сигнал не нужно рисовать.

    Закладки (bookmark) до завершения верификаций: оранжевый (#FF9800)
    Обычные кандидаты до верификаций:              жёлтый
    В1 + В2 пройдены (ПЭМИН):                      зелёный
    В1 или В2 провалена:                            None — не рисуем
    """
    is_bookmark = getattr(sig, 'detection_method', '') == 'bookmark'
    v1 = sig.verified_1
    v2 = sig.verified_2

    if v1 is None or (v1 and v2 is None):
        # Ожидание: закладки остаются оранжевыми, обычные — жёлтые
        return (255, 152, 0) if is_bookmark else (255, 220, 50)

    if v1 and v2:
        return (50, 220, 80)    # ПЭМИН подтверждён

    return None                 # В1 или В2 провалена — не рисуем
