import sys
import csv
import os
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTableWidget, QTableWidgetItem, QLabel,
                             QProgressBar, QMessageBox, QGroupBox, QHeaderView,
                             QApplication, QFileDialog, QDoubleSpinBox, QSpinBox,
                             QCheckBox, QFormLayout)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QColor
from core.workflow import MeasurementWorkflow
from core.config import PanoramaConfig
from core.sdr_controller import SDRController
from gui.spectrum_widget import SpectrumPlotWidget, _marker_color


class Worker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(float)
    data = pyqtSignal(object, object, object)
    action_needed = pyqtSignal(str, str, str)
    signals_updated = pyqtSignal()   # испускается после каждого изменения статуса сигнала
    error = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, workflow: MeasurementWorkflow):
        super().__init__()
        self.wf = workflow
        self.wf.on_status = self.status.emit
        self.wf.on_progress = self.progress.emit
        self.wf.on_data = lambda a, b, c: self.data.emit(a, b, c)
        self.wf.on_user_action_needed = self.action_needed.emit
        self.wf.on_signal_updated = self.signals_updated.emit

    def run(self):
        try:
            self.wf.run_full_cycle()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished_signal.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ПЭМИН Навигатор (RTL-SDR)")
        self.resize(1200, 800)

        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QGroupBox {
                font-weight: bold; border: 1px solid #444; border-radius: 5px;
                margin-top: 10px; padding-top: 10px; color: #e0e0e0;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; }
        """)

        self.cfg = PanoramaConfig()
        self.ctrl = SDRController()
        self.wf = None
        self.thread = None
        self.current_step = "idle"
        self._resetting = False

        self._init_ui()

    def _init_ui(self):
        w = QWidget()
        self.setCentralWidget(w)
        main_layout = QVBoxLayout(w)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Панель прогресса + стоп
        top_control_layout = QHBoxLayout()

        self.prog = QProgressBar()
        self.prog.setTextVisible(True)
        self.prog.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444; border-radius: 4px;
                text-align: center; color: white; background-color: #333;
            }
            QProgressBar::chunk { background-color: #2196F3; width: 10px; margin: 0.5px; }
        """)

        self.btn_stop = QPushButton("↺ СБРОС")
        self.btn_stop.setStyleSheet("""
            QPushButton { background-color: #D32F2F; color: white; font-weight: bold;
                          padding: 5px 15px; border-radius: 4px; }
            QPushButton:hover { background-color: #B71C1C; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._reset_to_start)

        top_control_layout.addWidget(self.prog, 1)
        top_control_layout.addWidget(self.btn_stop)
        main_layout.addLayout(top_control_layout)

        # Панель параметров измерения
        main_layout.addWidget(self._create_settings_panel())

        # График спектра
        self.plot = SpectrumPlotWidget()
        self.plot.freq_clicked.connect(self._on_graph_click)
        main_layout.addWidget(self.plot, 3)

        # Нижняя секция: таблица + управление
        bottom_section = QHBoxLayout()
        bottom_section.setSpacing(10)

        # Таблица результатов
        table_group = QGroupBox("Результаты измерений")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(5, 5, 5, 5)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Частота (МГц)", "Δ дБ", "ON дБ", "OFF дБ", "Статус"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #252525; alternate-background-color: #2d2d2d;
                color: #e0e0e0; gridline-color: #444; border: 1px solid #444;
            }
            QHeaderView::section {
                background-color: #333; color: #fff; padding: 4px;
                border: 1px solid #444; font-weight: bold;
            }
            QTableWidget::item:selected { background-color: #2196F3; color: white; }
        """)
        table_layout.addWidget(self.table)
        bottom_section.addWidget(table_group, 2)

        # Панель статуса и управления
        control_group = QGroupBox("Статус и Управление")
        control_layout = QVBoxLayout(control_group)
        control_layout.setContentsMargins(10, 10, 10, 10)
        control_layout.setSpacing(10)

        self.lbl_instruction = QLabel("Подключите SDR для начала работы.")
        self.lbl_instruction.setStyleSheet(
            "color: #e0e0e0; font-size: 13px; padding: 10px;"
            "background-color: #2b2b2b; border: 1px solid #444; border-radius: 4px;"
        )
        self.lbl_instruction.setWordWrap(True)
        self.lbl_instruction.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_instruction.setMinimumHeight(100)
        control_layout.addWidget(self.lbl_instruction)

        self.btn_save = QPushButton("💾 Сохранить отчет (CSV)")
        self.btn_save.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; font-weight: bold;
                          padding: 8px; border-radius: 4px; font-size: 12px; border: none; }
            QPushButton:hover { background-color: #388E3C; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_report)
        control_layout.addWidget(self.btn_save)

        control_layout.addStretch(1)

        self.btn_action = QPushButton("ПОДКЛЮЧИТЬ И НАЧАТЬ")
        self.btn_action.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; font-weight: bold;
                          padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled { background-color: #444; color: #888; }
        """)
        self.btn_action.clicked.connect(self._on_control_button_clicked)
        control_layout.addWidget(self.btn_action)

        bottom_section.addWidget(control_group, 1)
        main_layout.addLayout(bottom_section, 2)

    # ------------------------------------------------------------------
    # Панель параметров
    # ------------------------------------------------------------------

    def _create_settings_panel(self) -> QGroupBox:
        box = QGroupBox("Параметры измерения")
        box.setStyleSheet("""
            QGroupBox { font-weight: bold; border: 1px solid #444; border-radius: 5px;
                        margin-top: 10px; padding-top: 8px; color: #e0e0e0; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QDoubleSpinBox, QSpinBox {
                background-color: #333; color: #e0e0e0; border: 1px solid #555;
                border-radius: 3px; padding: 2px 4px; min-width: 70px;
            }
            QLabel { color: #ccc; font-size: 12px; }
            QCheckBox { color: #ccc; font-size: 12px; }
        """)

        layout = QHBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)

        def spin(min_v, max_v, val, step=1.0, decimals=1):
            s = QDoubleSpinBox()
            s.setRange(min_v, max_v)
            s.setValue(val)
            s.setSingleStep(step)
            s.setDecimals(decimals)
            return s

        # Частота начала
        layout.addWidget(QLabel("Нач. частота (МГц):"))
        self.spin_start_freq = spin(24, 1750, self.cfg.start_freq_hz / 1e6, 1.0, 2)
        layout.addWidget(self.spin_start_freq)

        # Частота конца
        layout.addWidget(QLabel("Кон. частота (МГц):"))
        self.spin_stop_freq = spin(25, 1750, self.cfg.stop_freq_hz / 1e6, 1.0, 2)
        layout.addWidget(self.spin_stop_freq)

        # Порог обнаружения
        layout.addWidget(QLabel("Порог (дБ):"))
        self.spin_threshold = spin(1.0, 40.0, self.cfg.threshold_db, 0.5, 1)
        layout.addWidget(self.spin_threshold)

        # Усиление SDR
        layout.addWidget(QLabel("Усиление SDR (дБ):"))
        self.spin_gain = spin(0.0, 50.0, self.cfg.sdr_gain_db, 0.5, 1)
        layout.addWidget(self.spin_gain)

        # Количество усреднений
        layout.addWidget(QLabel("Усредн.:"))
        self.spin_avg = QSpinBox()
        self.spin_avg.setRange(1, 100)
        self.spin_avg.setValue(self.cfg.averaging_count)
        self.spin_avg.setStyleSheet("""
            QSpinBox { background-color: #333; color: #e0e0e0; border: 1px solid #555;
                       border-radius: 3px; padding: 2px 4px; min-width: 55px; }
        """)
        layout.addWidget(self.spin_avg)

        # MaxHold
        self.chk_maxhold = QCheckBox("MaxHold")
        self.chk_maxhold.setChecked(self.cfg.use_max_hold)
        layout.addWidget(self.chk_maxhold)

        layout.addStretch(1)

        self._settings_widgets = [
            self.spin_start_freq, self.spin_stop_freq, self.spin_threshold,
            self.spin_gain, self.spin_avg, self.chk_maxhold,
        ]
        return box

    def _apply_settings_to_cfg(self):
        start = self.spin_start_freq.value() * 1e6
        stop  = self.spin_stop_freq.value() * 1e6
        if stop <= start:
            QMessageBox.warning(self, "Ошибка параметров",
                                "Конечная частота должна быть больше начальной.")
            return False

        self.cfg.start_freq_hz   = start
        self.cfg.stop_freq_hz    = stop
        self.cfg.threshold_db    = self.spin_threshold.value()
        self.cfg.sdr_gain_db     = self.spin_gain.value()
        self.cfg.averaging_count = self.spin_avg.value()
        self.cfg.use_max_hold     = self.chk_maxhold.isChecked()
        self.cfg.combine_triplets = True
        return True

    def _set_settings_enabled(self, enabled: bool):
        for w in self._settings_widgets:
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Сохранение отчёта
    # ------------------------------------------------------------------

    def _save_report(self):
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "Внимание", "Нет данных для сохранения.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"pemin_report_{timestamp}.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчет", default_name, "CSV Files (*.csv)"
        )

        if file_path:
            try:
                with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    headers = [
                        self.table.horizontalHeaderItem(i).text()
                        for i in range(self.table.columnCount())
                    ]
                    writer.writerow(headers)
                    for row in range(self.table.rowCount()):
                        row_data = []
                        for col in range(self.table.columnCount()):
                            item = self.table.item(row, col)
                            row_data.append(item.text() if item else "")
                        writer.writerow(row_data)
                QMessageBox.information(self, "Успех", f"Отчет сохранен:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{str(e)}")

    # ------------------------------------------------------------------
    # Управление процессом
    # ------------------------------------------------------------------

    def _reset_to_start(self):
        """Прерывает текущий процесс (если запущен) и возвращает программу в начальное состояние."""
        self._resetting = True
        if self.wf:
            self.wf.stop()
        # Не ждём завершения потока — он завершится сам через _on_thread_finished

        self._do_ui_reset()

    def _on_control_button_clicked(self):
        if self.current_step == "idle":
            self._connect_and_start()
        else:
            if self.wf:
                self.wf.resume()
                self.btn_action.setEnabled(False)
                self.lbl_instruction.setText("⏳ Выполнение измерения...")
                self.btn_stop.setEnabled(True)

    def _connect_and_start(self):
        if not self._apply_settings_to_cfg():
            return
        try:
            self.ctrl.connect()
            self.ctrl.configure(self.cfg)
            self._start_workflow()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка подключения", str(e))

    def _start_workflow(self):
        self.current_step = "running"
        self._set_settings_enabled(False)
        self.lbl_instruction.setText("⏳ <b>Запуск процесса...</b>")
        self.btn_action.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_save.setEnabled(False)
        self.prog.setValue(0)

        self.table.setRowCount(0)
        self.plot.clear()

        self.wf = MeasurementWorkflow(self.ctrl, self.cfg)
        self.thread = Worker(self.wf)

        Q = Qt.ConnectionType.QueuedConnection
        self.thread.status.connect(lambda s: self.lbl_instruction.setText(s), Q)
        self.thread.progress.connect(lambda v: self.prog.setValue(int(v)), Q)
        self.thread.data.connect(self._plot_data, Q)
        self.thread.action_needed.connect(self._on_action_needed, Q)
        self.thread.signals_updated.connect(self._refresh_markers, Q)
        self.thread.error.connect(lambda e: QMessageBox.critical(self, "Ошибка", e), Q)
        self.thread.finished_signal.connect(self._on_thread_finished, Q)

        self.thread.start()

    def _on_table_selection_changed(self):
        if not self.table.selectedItems():
            self.plot.clear_highlight()
            return
        row = self.table.currentRow()
        freq_item = self.table.item(row, 0)
        if freq_item is None:
            self.plot.clear_highlight()
            return
        signals = self.wf.signals if self.wf and hasattr(self.wf, "signals") else []
        if not signals:
            self.plot.clear_highlight()
            return
        try:
            freq_hz = float(freq_item.text()) * 1e6
        except ValueError:
            self.plot.clear_highlight()
            return
        sig = min(signals, key=lambda s: abs(s.frequency_hz - freq_hz))
        if _marker_color(sig) is not None:
            self.plot.set_highlight(sig.frequency_hz / 1e6)
        else:
            self.plot.clear_highlight()

    def _on_graph_click(self, freq_mhz: float):
        """Выделяет в таблице ближайший к freq_mhz сигнал с маркером на графике."""
        if not self.wf or not hasattr(self.wf, "signals") or not self.wf.signals:
            return

        # Порог: половина видимого диапазона / 20 — слишком далёкий клик игнорируем
        view_range = self.plot.plot.viewRange()[0]
        visible_span = abs(view_range[1] - view_range[0]) if view_range[1] else 20.0
        threshold_mhz = visible_span / 20.0

        visible = [(i, s) for i, s in enumerate(self.wf.signals)
                   if _marker_color(s) is not None]
        if not visible:
            return

        nearest_i, nearest_sig = min(visible,
                                     key=lambda x: abs(x[1].frequency_hz / 1e6 - freq_mhz))
        if abs(nearest_sig.frequency_hz / 1e6 - freq_mhz) > threshold_mhz:
            self.plot.clear_highlight()
            self.table.clearSelection()
            return

        self.plot.set_highlight(nearest_sig.frequency_hz / 1e6)

        # Выделяем строку в таблице по частоте
        target_hz = nearest_sig.frequency_hz
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                try:
                    if abs(float(item.text()) * 1e6 - target_hz) < 100:
                        self.table.blockSignals(True)
                        self.table.selectRow(row)
                        self.table.blockSignals(False)
                        self.table.scrollTo(self.table.model().index(row, 0))
                        break
                except ValueError:
                    pass

    def _refresh_markers(self):
        """Перерисовывает маркеры на графике по текущему состоянию сигналов.
        Вызывается после каждого изменения статуса сигнала во время верификации."""
        if self.wf and hasattr(self.wf, "signals"):
            self.plot.plot_signals(self.wf.signals)
            self._update_table_from_signals(self.wf.signals)

    def _on_action_needed(self, title, instruction, btn_text):
        self.current_step = "waiting"

        color = "#FF9800"
        if "ЗАВЕРШЕНА" in title or "ЗАВЕРШЕНО" in title:
            color = "#4CAF50"
        elif "ОШИБКА" in title or "СТОП" in title:
            color = "#F44336"

        html_text = f"<h3 style='color: {color}; margin-bottom: 5px;'>{title}</h3>"
        html_text += f"<div style='line-height: 1.4;'>{instruction.replace(chr(10), '<br>')}</div>"

        self.lbl_instruction.setText(html_text)
        self.btn_action.setText(btn_text)
        self.btn_action.setEnabled(True)
        self.btn_stop.setEnabled(True)   # сброс доступен всегда во время процесса

        if "ЗАВЕРШЕНА" in title or "ЗАВЕРШЕНО" in title:
            self.btn_action.setStyleSheet("""
                QPushButton { background-color: #4CAF50; color: white; font-weight: bold;
                              padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
                QPushButton:hover { background-color: #388E3C; }
            """)
            self.btn_save.setEnabled(True)
        else:
            self.btn_action.setStyleSheet("""
                QPushButton { background-color: #FF9800; color: white; font-weight: bold;
                              padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
                QPushButton:hover { background-color: #F57C00; }
            """)

        if self.wf and hasattr(self.wf, "signals"):
            self._update_table_only()

    def _do_ui_reset(self):
        self.current_step = "idle"
        self.wf = None
        self.thread = None
        self._resetting = False

        self.plot.clear()
        self.table.setRowCount(0)
        self.prog.setValue(0)

        self.lbl_instruction.setText("Подключите SDR для начала работы.")
        self.lbl_instruction.setStyleSheet(
            "color: #e0e0e0; font-size: 13px; padding: 10px;"
            "background-color: #2b2b2b; border: 1px solid #444; border-radius: 4px;"
        )
        self.btn_action.setText("ПОДКЛЮЧИТЬ И НАЧАТЬ")
        self.btn_action.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; font-weight: bold;
                          padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled { background-color: #444; color: #888; }
        """)
        self.btn_action.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_save.setEnabled(False)
        self._set_settings_enabled(True)

    def _on_thread_finished(self):
        if self._resetting:
            # Сброс уже выполнен через _reset_to_start, просто игнорируем
            self._resetting = False
            return

        self.btn_stop.setEnabled(True)
        self.current_step = "idle"
        self._set_settings_enabled(True)
        self.btn_action.setText("НОВЫЙ ПОИСК")
        self.btn_action.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; font-weight: bold;
                          padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
            QPushButton:hover { background-color: #1976D2; }
        """)

    def _plot_data(self, on, off, diff):
        f_mhz = on.frequencies_hz / 1e6
        x_min, x_max = float(f_mhz.min()), float(f_mhz.max())

        self.plot.clear()
        self.plot.set_freq_range(x_min, x_max)
        self.plot.add("ON (Test)", f_mhz, on.amplitudes_db, "y")
        self.plot.add("OFF (Noise)", f_mhz, off.amplitudes_db, "b")
        self.plot.add("Difference", f_mhz, diff, "r", fill=(255, 0, 0, 50))
        self.plot.set_threshold(self.cfg.threshold_db, [x_min, x_max])

        if self.wf and hasattr(self.wf, "signals"):
            self._update_table_from_signals(self.wf.signals)
            self.plot.plot_signals(self.wf.signals)

        # Reset в конце, когда все элементы уже добавлены
        self.plot.reset_zoom()

    def _update_table_only(self):
        if self.wf and hasattr(self.wf, "signals"):
            self._update_table_from_signals(self.wf.signals)

    # ------------------------------------------------------------------
    # Таблица результатов
    # ------------------------------------------------------------------

    def _update_table_from_signals(self, signals):
        """
        Цветовая схема статусов согласована с workflow.py:

        status_color → значение в таблице
        ─────────────────────────────────────────────────────────────
        "yellow"  → ожидание / В1 OK (промежуточно)
        "green"   → ПЭМИН (В1 + В2 пройдены)
        "red"     → нестабильная помеха (В1 провален, В2 пройден)
        "blue"    → внешний сигнал / двойной брак (В1 OK + В2 fail
                    или оба провалены)
        ─────────────────────────────────────────────────────────────
        """
        # Цвета (hex, мягкая палитра для тёмной темы)
        COLOR_WAIT    = "#9E9E9E"   # Серый — ожидание
        COLOR_SUCCESS = "#66BB6A"   # Зелёный — ПЭМИН
        COLOR_FAIL_V1 = "#EF5350"   # Красный — нестабильный (В1 fail)
        COLOR_EXTERNAL = "#42A5F5"  # Синий — внешний / двойной брак
        COLOR_WARN    = "#FFCA28"   # Янтарный — промежуточный (В1 OK, ждём В2)

        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)

        count = len(signals)
        self.table.setRowCount(count)

        if count == 0:
            self.table.setUpdatesEnabled(True)
            self.table.repaint()
            return

        for i, s in enumerate(signals):
            item_freq = QTableWidgetItem(f"{s.frequency_hz / 1e6:.4f}")
            item_freq.setData(Qt.ItemDataRole.UserRole, i)  # индекс для поиска по клику
            item_diff = QTableWidgetItem(f"{s.amplitude_diff_db:.1f}")
            item_on   = QTableWidgetItem(f"{s.amplitude_on_db:.1f}")
            item_off  = QTableWidgetItem(f"{s.amplitude_off_db:.1f}")

            # Определяем статус и цвет по status_color из workflow
            color_map = {
                "yellow": (COLOR_WARN,     "⏳ В1 OK"),
                "green":  (COLOR_SUCCESS,  "✅ ПЭМИН"),
                "red":    (COLOR_FAIL_V1,  "❌ Брак (В1)"),
                "blue":   (COLOR_EXTERNAL, "〇 Внешний / Двойной брак"),
            }

            # Уточняем текст статуса для промежуточных состояний
            v1 = s.verified_1
            v2 = s.verified_2

            if v1 is None and v2 is None:
                status_text = "⏳ Ожидание"
                color_hex = COLOR_WAIT
            elif v1 is not None and v2 is None:
                # После В1, до В2
                if v1:
                    status_text = "⏳ В1 OK"
                    color_hex = COLOR_WARN
                else:
                    status_text = "❌ Брак (В1)"
                    color_hex = COLOR_FAIL_V1
            else:
                # Финальный результат: берём из color_map по status_color
                color_hex, status_text = color_map.get(
                    s.status_color, (COLOR_WAIT, "—")
                )
                # Уточняем текст для синего: различаем два случая
                if s.status_color == "blue":
                    if v1 and not v2:
                        status_text = "〇 Внешний (В2)"
                    else:
                        status_text = "〇 Двойной брак"

            item_status = QTableWidgetItem(status_text)
            item_status.setForeground(QColor(color_hex))

            self.table.setItem(i, 0, item_freq)
            self.table.setItem(i, 1, item_diff)
            self.table.setItem(i, 2, item_on)
            self.table.setItem(i, 3, item_off)
            self.table.setItem(i, 4, item_status)

        self.table.setUpdatesEnabled(True)
        self.table.setSortingEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())