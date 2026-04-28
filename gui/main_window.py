import sys
import csv
import os
import types
import numpy as np
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTableWidget, QTableWidgetItem, QLabel,
                             QProgressBar, QMessageBox, QGroupBox, QHeaderView,
                             QApplication, QFileDialog, QDoubleSpinBox, QSpinBox,
                             QCheckBox, QFormLayout, QStackedWidget)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QColor, QAction, QActionGroup
from core.config import PanoramaConfig
from core.backends import BaseInstrument, RtlSdrBackend, DemoSimulator
from core.models import Spectrum, PEMINSignal
from core.methods import PanoramaDiffWorkflow, HarmonicSearchWorkflow
from core.audio_monitor import AudioMonitor
from core.zero_span import ZeroSpanWorker
from gui.spectrum_widget import SpectrumPlotWidget, _marker_color
from gui.expert_panel import ExpertPanel
from gui.zero_span_widget import ZeroSpanWidget
from gui.live_widget import LiveWidget
from core.live_worker import LiveWorker


class Worker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(float)
    data = pyqtSignal(object, object, object)
    off_spectrum_ready = pyqtSignal(object)   # OFF-спектр сразу после захвата
    action_needed = pyqtSignal(str, str, str)
    signals_updated = pyqtSignal()   # испускается после каждого изменения статуса сигнала
    error = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, workflow):
        super().__init__()
        self.wf = workflow
        self.wf.on_status = self.status.emit
        self.wf.on_progress = self.progress.emit
        self.wf.on_data = lambda a, b, c: self.data.emit(a, b, c)
        self.wf.on_user_action_needed = self.action_needed.emit
        self.wf.on_signal_updated = self.signals_updated.emit
        self.wf.on_off_spectrum = self.off_spectrum_ready.emit

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
        self.setWindowTitle("ПЭМИН Детектор (RTL-SDR)")
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
        self.ctrl: BaseInstrument = RtlSdrBackend()
        self.wf = None
        self.thread = None
        self.current_step = "idle"
        self._resetting = False
        self._last_on = None
        self._last_off = None
        self._last_diff = None
        self._current_action_title: str = ""
        self._audio = AudioMonitor()
        self._zs_worker: ZeroSpanWorker | None = None
        self._live_worker: LiveWorker | None = None
        self._overlay_worker: LiveWorker | None = None
        self._panorama_preview_worker: LiveWorker | None = None
        self._bookmark_freqs_hz: list[float] = []   # частоты (Гц), отмеченные в live

        self.scan_mode = "full"   # "full"|"quick"|"harmonic"|"simulator"|"demo"|"live"|"live_sim"

        self._init_ui()
        self._setup_menu_bar()

    def _setup_menu_bar(self):
        mb = self.menuBar()
        mb.setStyleSheet("""
            QMenuBar { background-color: #2b2b2b; color: #e0e0e0; }
            QMenuBar::item:selected { background-color: #444; }
            QMenu { background-color: #2b2b2b; color: #e0e0e0; border: 1px solid #555; }
            QMenu::item:selected { background-color: #3a3a3a; }
            QMenu::separator { height: 1px; background: #555; margin: 3px 0; }
        """)

        # ── Режим ─────────────────────────────────────────────────────
        menu_mode = mb.addMenu("Режим")

        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)

        self.act_mode_diff = QAction("Метод разности панорам  (ON − OFF)", self)
        self.act_mode_diff.setCheckable(True)
        self.act_mode_diff.setChecked(True)
        self.act_mode_diff.triggered.connect(lambda: self._set_scan_mode("full"))
        mode_group.addAction(self.act_mode_diff)
        menu_mode.addAction(self.act_mode_diff)

        self.act_mode_quick = QAction("Быстрое обнаружение  (без верификации)", self)
        self.act_mode_quick.setCheckable(True)
        self.act_mode_quick.triggered.connect(lambda: self._set_scan_mode("quick"))
        mode_group.addAction(self.act_mode_quick)
        menu_mode.addAction(self.act_mode_quick)

        menu_mode.addSeparator()

        self.act_mode_harmonic = QAction("〜  Метод поиска по гармоникам", self)
        self.act_mode_harmonic.setCheckable(True)
        self.act_mode_harmonic.triggered.connect(lambda: self._set_scan_mode("harmonic"))
        mode_group.addAction(self.act_mode_harmonic)
        menu_mode.addAction(self.act_mode_harmonic)

        self.act_mode_corr = QAction("Параметрически-корреляционный метод  (не реализован)", self)
        self.act_mode_corr.setCheckable(True)
        self.act_mode_corr.setEnabled(False)
        mode_group.addAction(self.act_mode_corr)
        menu_mode.addAction(self.act_mode_corr)

        self.act_mode_audio = QAction("Аудио-визуальный метод  (не реализован)", self)
        self.act_mode_audio.setCheckable(True)
        self.act_mode_audio.setEnabled(False)
        mode_group.addAction(self.act_mode_audio)
        menu_mode.addAction(self.act_mode_audio)

        menu_mode.addSeparator()

        self.act_mode_live = QAction("📡  Прямой эфир  (SDR)", self)
        self.act_mode_live.setCheckable(True)
        self.act_mode_live.triggered.connect(lambda: self._set_scan_mode("live"))
        mode_group.addAction(self.act_mode_live)
        menu_mode.addAction(self.act_mode_live)

        self.act_mode_live_sim = QAction("📡  Прямой эфир  (симулятор)", self)
        self.act_mode_live_sim.setCheckable(True)
        self.act_mode_live_sim.triggered.connect(lambda: self._set_scan_mode("live_sim"))
        mode_group.addAction(self.act_mode_live_sim)
        menu_mode.addAction(self.act_mode_live_sim)

        menu_mode.addSeparator()

        self.act_mode_simulator = QAction("Симулятор  (без железа)", self)
        self.act_mode_simulator.setCheckable(True)
        self.act_mode_simulator.triggered.connect(lambda: self._set_scan_mode("simulator"))
        mode_group.addAction(self.act_mode_simulator)
        menu_mode.addAction(self.act_mode_simulator)

        self.act_mode_demo = QAction("Демо-режим  (загрузить архив)", self)
        self.act_mode_demo.setCheckable(True)
        self.act_mode_demo.triggered.connect(lambda: self._set_scan_mode("demo"))
        mode_group.addAction(self.act_mode_demo)
        menu_mode.addAction(self.act_mode_demo)

        # ── Действие ──────────────────────────────────────────────────
        menu_action = mb.addMenu("Действие")

        self.act_load = QAction("Загрузить измерение", self)
        self.act_load.setShortcut("Ctrl+O")
        self.act_load.triggered.connect(self._load_measurement)
        menu_action.addAction(self.act_load)

        self.act_compare = QAction("⚖  Сравнить две сессии", self)
        self.act_compare.triggered.connect(self._compare_sessions)
        menu_action.addAction(self.act_compare)

        menu_action.addSeparator()

        self.act_save = QAction("Экспорт сигналов (CSV)", self)
        self.act_save.setShortcut("Ctrl+S")
        self.act_save.setEnabled(False)
        self.act_save.triggered.connect(self._save_report)
        menu_action.addAction(self.act_save)

        self.act_export_spectrum = QAction("Экспорт спектра (NPZ)", self)
        self.act_export_spectrum.setShortcut("Ctrl+E")
        self.act_export_spectrum.setEnabled(False)
        self.act_export_spectrum.triggered.connect(self._export_spectrum)
        menu_action.addAction(self.act_export_spectrum)

    def _set_scan_mode(self, mode: str):
        self.scan_mode = mode
        if mode == "full":
            self.btn_action.setText("ПОДКЛЮЧИТЬ И НАЧАТЬ")
        elif mode == "quick":
            self.btn_action.setText("БЫСТРОЕ СКАНИРОВАНИЕ")
        elif mode == "harmonic":
            self.btn_action.setText("ПОИСК ПО ГАРМОНИКАМ")
        elif mode == "simulator":
            self.btn_action.setText("ЗАПУСТИТЬ СИМУЛЯТОР")
        elif mode == "demo":
            self.btn_action.setText("ЗАГРУЗИТЬ АРХИВ")
        elif mode in ("live", "live_sim"):
            self.btn_action.setText("ЗАПУСТИТЬ ПРЯМОЙ ЭФИР")
        # Колонка «Гармоники» — только для harmonic-режима
        self.table.setColumnHidden(4, mode != "harmonic")

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

        # График спектра / Zero Span (переключаются через QStackedWidget)
        self.plot = SpectrumPlotWidget()
        self.plot.freq_clicked.connect(self._on_graph_click)
        self.plot.live_overlay_toggled.connect(self._on_panorama_live_toggled)
        self.plot.freq_mark_added.connect(self._on_panorama_freq_marked)
        self.zero_span_widget = ZeroSpanWidget()
        self.live_widget = LiveWidget()
        self.live_widget.freq_marked.connect(self._on_live_freq_marked)
        self.live_widget.freq_selected.connect(self._on_live_graph_freq_clicked)
        self._spectrum_stack = QStackedWidget()
        self._spectrum_stack.addWidget(self.plot)            # index 0 — спектр
        self._spectrum_stack.addWidget(self.zero_span_widget)  # index 1 — zero span
        self._spectrum_stack.addWidget(self.live_widget)     # index 2 — прямой эфир
        main_layout.addWidget(self._spectrum_stack, 3)

        # Нижняя секция: таблица + управление
        bottom_section = QHBoxLayout()
        bottom_section.setSpacing(10)

        # Таблица результатов
        table_group = QGroupBox("Результаты измерений")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(5, 5, 5, 5)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Частота (МГц)", "Δ дБ", "ON дБ", "OFF дБ", "Гармоники", "Статус"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setColumnHidden(4, True)   # «Гармоники» — скрыта до активации метода
        self.table.setAlternatingRowColors(True)
        self.table.setMouseTracking(True)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemEntered.connect(self._on_table_item_hover)
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
        self.lbl_instruction.setMinimumHeight(80)
        control_layout.addWidget(self.lbl_instruction)

        self.expert_panel = ExpertPanel()
        self.expert_panel.signal_modified.connect(self._on_expert_signal_modified)
        self.expert_panel.zero_span_started.connect(self._on_zero_span_start)
        self.expert_panel.zero_span_stopped.connect(self._on_zero_span_stop)
        control_layout.addWidget(self.expert_panel)

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

        # Режим одной полосы SDR (только для live и preview)
        self.chk_single_bw = QCheckBox("Полоса SDR (2 МГц)")
        self.chk_single_bw.setToolTip(
            "Показывать только одну полосу пропускания SDR (~2 МГц)\n"
            "вместо полного диапазона. Значительно ускоряет обновление."
        )
        layout.addWidget(self.chk_single_bw)

        layout.addStretch(1)

        self._settings_widgets = [
            self.spin_start_freq, self.spin_stop_freq, self.spin_threshold,
            self.spin_gain, self.spin_avg, self.chk_maxhold, self.chk_single_bw,
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

    def _export_spectrum(self):
        if self._last_on is None:
            QMessageBox.warning(self, "Внимание", "Нет данных спектра для экспорта.")
            return

        import numpy as np
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"pemin_spectrum_{timestamp}.npz"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт спектра", default_name, "NumPy Archive (*.npz)"
        )
        if not file_path:
            return

        try:
            signals = self.wf.signals if self.wf and hasattr(self.wf, "signals") else []
            sig_freqs = np.array([s.frequency_hz for s in signals])
            sig_diffs = np.array([s.amplitude_diff_db for s in signals])
            sig_on    = np.array([s.amplitude_on_db for s in signals])
            sig_off   = np.array([s.amplitude_off_db for s in signals])
            sig_v1    = np.array([s.verified_1 if s.verified_1 is not None else float("nan")
                                  for s in signals])
            sig_v2    = np.array([s.verified_2 if s.verified_2 is not None else float("nan")
                                  for s in signals])
            sig_status = np.array([s.status_color if s.status_color else "" for s in signals])

            np.savez_compressed(
                file_path,
                # Спектры
                frequencies_hz=self._last_on.frequencies_hz,
                amplitudes_on_db=self._last_on.amplitudes_db,
                amplitudes_off_db=self._last_off.amplitudes_db,
                diff_db=self._last_diff,
                # Обнаруженные сигналы
                signal_frequencies_hz=sig_freqs,
                signal_diff_db=sig_diffs,
                signal_on_db=sig_on,
                signal_off_db=sig_off,
                signal_verified_1=sig_v1,
                signal_verified_2=sig_v2,
                signal_status=sig_status,
                # Параметры измерения
                cfg_start_hz=np.float64(self.cfg.start_freq_hz),
                cfg_stop_hz=np.float64(self.cfg.stop_freq_hz),
                cfg_threshold_db=np.float64(self.cfg.threshold_db),
                cfg_averaging_count=np.int32(self.cfg.averaging_count),
                cfg_sdr_gain_db=np.float64(self.cfg.sdr_gain_db),
                cfg_use_max_hold=np.bool_(self.cfg.use_max_hold),
                cfg_rbw_hz=np.float64(self._last_on.rbw_hz),
                timestamp=np.float64(self._last_on.timestamp),
            )
            QMessageBox.information(self, "Успех", f"Спектр сохранён:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{str(e)}")

    # ------------------------------------------------------------------
    # Управление процессом
    # ------------------------------------------------------------------

    def _reset_to_start(self):
        """Прерывает текущий процесс и возвращает программу в начальное состояние."""
        self._resetting = True
        self.btn_action.setEnabled(False)   # блокируем повторный запуск

        self._stop_panorama_preview()
        self._stop_live()
        if self.wf:
            self.wf.stop()

        # Ждём завершения потока перед освобождением SDR
        # (предотвращает Segmentation fault при быстром нажатии Сброс → Старт)
        if self.thread is not None and self.thread.isRunning():
            self.thread.wait(3000)

        self._do_ui_reset()

    def _on_control_button_clicked(self):
        if self.current_step == "idle":
            if self.scan_mode == "demo":
                self._load_measurement()
            elif self.scan_mode in ("live", "live_sim"):
                self._start_live()
            else:
                self._connect_and_start()
        elif self.current_step == "live_preview":
            self._launch_measurement_from_preview()
            return
        elif self.current_step == "live":
            return  # в live-режиме нет фаз для перехода; остановка — через СБРОС
        else:
            # Перед возобновлением — переключаем тест-сигнал симулятора если нужно
            if isinstance(self.ctrl, DemoSimulator):
                title = self._current_action_title
                if "ФОН ИЗМЕРЕН" in title:
                    self.ctrl.test_active = True
                elif "ВЕРИФИКАЦИЯ 1 ЗАВЕРШЕНА" in title:
                    self.ctrl.test_active = False
            if self.wf:
                self.wf.resume()
                self.btn_action.setEnabled(False)
                self.lbl_instruction.setText("⏳ Выполнение измерения...")
                self.btn_stop.setEnabled(True)

    def _connect_and_start(self):
        if not self._apply_settings_to_cfg():
            return
        self.cfg.skip_verification = (self.scan_mode == "quick")

        if self.scan_mode == "simulator":
            self._start_simulator()
            return

        try:
            self.ctrl.close()
        except Exception:
            pass
        try:
            self.ctrl = RtlSdrBackend()
            self.ctrl.connect()
            self.ctrl.configure(self.cfg)
            self._start_panorama_preview()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка подключения", str(e))

    def _start_live(self):
        if not self._apply_settings_to_cfg():
            return

        use_sim = (self.scan_mode == "live_sim")
        if use_sim:
            ctrl = DemoSimulator()
            ctrl.test_active = True
        else:
            try:
                self.ctrl.close()
            except Exception:
                pass
            try:
                ctrl = RtlSdrBackend()
                ctrl.connect()
                self.ctrl = ctrl
            except Exception as e:
                QMessageBox.critical(self, "Ошибка подключения", str(e))
                return

        from copy import copy as _copy
        live_cfg = _copy(self.cfg)
        live_cfg.fft_size = 2048
        live_cfg.averaging_count = 1
        live_cfg.use_max_hold = False

        if self.chk_single_bw.isChecked():
            center = (live_cfg.start_freq_hz + live_cfg.stop_freq_hz) / 2
            half_bw = 1_000_000
            live_cfg.start_freq_hz = max(center - half_bw, 24e6)
            live_cfg.stop_freq_hz  = min(center + half_bw, 1_750e6)

        if use_sim:
            ctrl._MEASURE_DELAY_S = 0.0

        self.current_step = "live"
        # Блокируем всё кроме частотного диапазона — его можно менять во время live
        for w in self._settings_widgets:
            if w not in (self.spin_start_freq, self.spin_stop_freq):
                w.setEnabled(False)
        self.btn_action.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._stop_zero_span()
        self.live_widget.clear()
        self.live_widget.clear_marks()
        self._bookmark_freqs_hz.clear()
        self._spectrum_stack.setCurrentIndex(2)
        self.expert_panel.set_zero_span_active(False)
        self.expert_panel.enable_remeasure(False)

        src = "симулятор" if use_sim else "SDR"
        self.lbl_instruction.setText(
            f"<b>📡 Прямой эфир активен ({src})</b><br>"
            f"<span style='color:#aaa'>"
            f"{live_cfg.start_freq_hz / 1e6:.2f} – {live_cfg.stop_freq_hz / 1e6:.2f} МГц<br>"
            f"Диапазон частот можно изменить в панели выше.<br>"
            f"Нажмите ↺ СБРОС для остановки</span>"
        )

        # Подключаем обновление диапазона при изменении частот в live-режиме
        self.spin_start_freq.valueChanged.connect(self._on_live_freq_range_changed)
        self.spin_stop_freq.valueChanged.connect(self._on_live_freq_range_changed)

        self._live_worker = LiveWorker(ctrl, live_cfg)
        Q = Qt.ConnectionType.QueuedConnection
        self._live_worker.spectrum_ready.connect(self._on_live_spectrum, Q)
        self._live_worker.error.connect(
            lambda e: QMessageBox.critical(self, "Ошибка Live", e), Q
        )
        self._live_worker.start()

    def _on_live_freq_range_changed(self) -> None:
        """Обновляет диапазон live-захвата при изменении спинбоксов в режиме прямого эфира."""
        if self.current_step != "live" or self._live_worker is None:
            return
        start_hz = self.spin_start_freq.value() * 1e6
        stop_hz  = self.spin_stop_freq.value() * 1e6
        if stop_hz <= start_hz + 100e3:
            return

        from copy import copy as _copy
        live_cfg = _copy(self.cfg)
        live_cfg.start_freq_hz = start_hz
        live_cfg.stop_freq_hz  = stop_hz
        live_cfg.fft_size = 2048
        live_cfg.averaging_count = 1
        live_cfg.use_max_hold = False
        if self.chk_single_bw.isChecked():
            center = (start_hz + stop_hz) / 2
            live_cfg.start_freq_hz = max(center - 1_000_000, 24e6)
            live_cfg.stop_freq_hz  = min(center + 1_000_000, 1_750e6)
        self._live_worker.update_config(live_cfg)
        self.live_widget._x_initialized = False   # сбросить диапазон оси X

    def _stop_live(self) -> None:
        if self._live_worker is not None:
            self._live_worker.stop()
            self._live_worker.wait(2000)
            self._live_worker = None

    def _on_live_spectrum(self, freqs_hz, amps_db) -> None:
        self.live_widget.update_spectrum(freqs_hz, amps_db)

    def _start_simulator(self):
        sim = DemoSimulator()
        sim.configure(self.cfg)
        sim._MEASURE_DELAY_S = 0.0
        self.ctrl = sim
        self._start_panorama_preview()

    def _start_panorama_preview(self) -> None:
        """Запускает live-просмотр спектра поверх графика панорамы."""
        self.current_step = "live_preview"
        self._set_settings_enabled(False)
        self.btn_action.setText("▶  ЗАПУСТИТЬ ИЗМЕРЕНИЕ ПАНОРАМЫ")
        self.btn_action.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self._stop_zero_span()
        self._spectrum_stack.setCurrentIndex(0)
        self.expert_panel.set_zero_span_active(False)
        self.expert_panel.enable_remeasure(False)
        self.plot.clear()

        from copy import copy as _cp
        prev_cfg = _cp(self.cfg)
        prev_cfg.fft_size = 2048
        prev_cfg.averaging_count = 1
        prev_cfg.use_max_hold = False

        # Применяем режим одной полосы, если включён
        if self.chk_single_bw.isChecked():
            center = (prev_cfg.start_freq_hz + prev_cfg.stop_freq_hz) / 2
            half_bw = 1_000_000
            prev_cfg.start_freq_hz = max(center - half_bw, 24e6)
            prev_cfg.stop_freq_hz  = min(center + half_bw, 1_750e6)

        self._panorama_preview_worker = LiveWorker(self.ctrl, prev_cfg)
        Q = Qt.ConnectionType.QueuedConnection
        self._panorama_preview_worker.spectrum_ready.connect(
            self._on_panorama_preview_spectrum, Q
        )
        self._panorama_preview_worker.error.connect(
            lambda e: QMessageBox.critical(self, "Ошибка Preview", e), Q
        )
        self._panorama_preview_worker.start()

        self._refresh_bookmark_table()

        self.lbl_instruction.setText(
            "<b>📡 Прямой эфир активен</b><br>"
            "<span style='color:#aaa'>Наблюдайте спектр. При необходимости — "
            "переключите режим источника сигнала.<br>"
            "Нажмите <b>▶ ЗАПУСТИТЬ ИЗМЕРЕНИЕ ПАНОРАМЫ</b> когда готовы.</span>"
        )

    def _stop_panorama_preview(self) -> None:
        if self._panorama_preview_worker is not None:
            self._panorama_preview_worker.stop()
            self._panorama_preview_worker.wait(2000)
            self._panorama_preview_worker = None

    def _on_panorama_preview_spectrum(self, freqs_hz, amps_db) -> None:
        self.plot.add("Прямой эфир", freqs_hz / 1e6, amps_db, "#39FF14", width=1)

    def _launch_measurement_from_preview(self) -> None:
        """Переход от live preview к реальному измерению панорамы."""
        self._stop_panorama_preview()
        try:
            self.ctrl.configure(self.cfg)
        except Exception:
            pass
        if isinstance(self.ctrl, DemoSimulator):
            self.ctrl._MEASURE_DELAY_S = 0.25
        self._start_workflow()

    def _make_workflow(self):
        if self.scan_mode == "harmonic":
            return HarmonicSearchWorkflow(self.ctrl, self.cfg)
        return PanoramaDiffWorkflow(
            self.ctrl, self.cfg,
            preset_candidates_hz=list(self._bookmark_freqs_hz),
        )

    def _start_workflow(self):
        self.current_step = "running"
        self._set_settings_enabled(False)
        self.lbl_instruction.setText("⏳ <b>Запуск процесса...</b>")
        self.btn_action.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.act_save.setEnabled(False)
        self.act_export_spectrum.setEnabled(False)
        self.prog.setValue(0)
        self._stop_zero_span()
        self._spectrum_stack.setCurrentIndex(0)
        self.expert_panel.set_zero_span_active(False)
        self.expert_panel.set_instrument(self.ctrl)
        self.expert_panel.enable_remeasure(False)

        self.table.setRowCount(0)
        self._stop_overlay()
        self.plot.enable_live_overlay_btn(False)
        self.plot.clear()

        self.wf = self._make_workflow()
        self.thread = Worker(self.wf)

        Q = Qt.ConnectionType.QueuedConnection
        self.thread.status.connect(lambda s: self.lbl_instruction.setText(s), Q)
        self.thread.progress.connect(lambda v: self.prog.setValue(int(v)), Q)
        self.thread.data.connect(self._plot_data, Q)
        self.thread.off_spectrum_ready.connect(self._on_off_spectrum_ready, Q)
        self.thread.action_needed.connect(self._on_action_needed, Q)
        self.thread.signals_updated.connect(self._refresh_markers, Q)
        self.thread.error.connect(lambda e: QMessageBox.critical(self, "Ошибка", e), Q)
        self.thread.finished_signal.connect(self._on_thread_finished, Q)

        self.thread.start()

    def _on_off_spectrum_ready(self, off_spec) -> None:
        """Показывает OFF-спектр сразу после захвата фона, до ON-измерения."""
        f_mhz = off_spec.frequencies_hz / 1e6
        x_min, x_max = float(f_mhz.min()), float(f_mhz.max())
        self.plot.clear()
        self.plot.set_freq_range(x_min, x_max)
        self.plot.add("OFF (фон)", f_mhz, off_spec.amplitudes_db, "b")
        self.plot.set_threshold(self.cfg.threshold_db, [x_min, x_max])
        self.plot.reset_zoom()

    def _on_table_selection_changed(self):
        if not self.table.selectedItems():
            self.plot.clear_highlight()
            self.expert_panel.clear_signal()
            return
        row = self.table.currentRow()
        freq_item = self.table.item(row, 0)
        if freq_item is None:
            self.plot.clear_highlight()
            self.expert_panel.clear_signal()
            return

        # В режиме прямого эфира — перемещаем live-график к выбранной частоте
        if self.current_step == "live":
            try:
                freq_mhz = float(freq_item.text())
                vb = self.live_widget._pw.getPlotItem().getViewBox()
                x_range = vb.viewRange()[0]
                half_span = (x_range[1] - x_range[0]) / 2
                vb.setXRange(freq_mhz - half_span, freq_mhz + half_span, padding=0)
            except (ValueError, AttributeError):
                pass
            return

        signals = self.wf.signals if self.wf and hasattr(self.wf, "signals") else []
        if not signals:
            self.plot.clear_highlight()
            self.expert_panel.clear_signal()
            return
        try:
            freq_hz = float(freq_item.text()) * 1e6
        except ValueError:
            self.plot.clear_highlight()
            self.expert_panel.clear_signal()
            return
        idx = min(range(len(signals)), key=lambda i: abs(signals[i].frequency_hz - freq_hz))
        sig = signals[idx]
        if _marker_color(sig) is not None:
            freq_mhz = sig.frequency_hz / 1e6
            self.plot.set_highlight(freq_mhz)
            self.plot.pan_to(freq_mhz)
        else:
            self.plot.clear_highlight()
        self.expert_panel.set_signal(sig, idx)

    def _on_table_item_hover(self, item):
        """Подсветка частоты на графике при наведении на строку в таблице."""
        row = item.row()
        freq_item = self.table.item(row, 0)
        if freq_item is None:
            self.plot.clear_highlight()
            return
        try:
            freq_mhz = float(freq_item.text())
        except ValueError:
            self.plot.clear_highlight()
            return
        
        # В режиме live — просто панируем к частоте
        if self.current_step == "live":
            try:
                vb = self.live_widget._pw.getPlotItem().getViewBox()
                x_range = vb.viewRange()[0]
                half_span = (x_range[1] - x_range[0]) / 2
                vb.setXRange(freq_mhz - half_span, freq_mhz + half_span, padding=0)
            except (ValueError, AttributeError):
                pass
            return
        
        # В режиме панорамы — подсвечиваем частоту
        signals = self.wf.signals if self.wf and hasattr(self.wf, "signals") else []
        if not signals:
            # Для bookmark-сигналов до начала измерения
            for bm_freq in self._bookmark_freqs_hz:
                if abs(bm_freq / 1e6 - freq_mhz) < 0.01:
                    self.plot.set_highlight(freq_mhz)
                    self.plot.pan_to(freq_mhz)
                    return
            self.plot.clear_highlight()
            return
        
        freq_hz = freq_mhz * 1e6
        idx = min(range(len(signals)), key=lambda i: abs(signals[i].frequency_hz - freq_hz))
        sig = signals[idx]
        if abs(signals[idx].frequency_hz - freq_hz) < 1e6:
            if _marker_color(sig) is not None:
                self.plot.set_highlight(freq_mhz)
                self.plot.pan_to(freq_mhz)
            else:
                self.plot.clear_highlight()
        else:
            self.plot.clear_highlight()

    def _on_live_graph_freq_clicked(self, freq_mhz: float) -> None:
        """При клике на live-графике (вне режима меток) — выделяем строку в таблице."""
        if not self._bookmark_freqs_hz:
            return
        freq_hz = freq_mhz * 1e6
        nearest_hz = min(self._bookmark_freqs_hz, key=lambda f: abs(f - freq_hz))
        threshold_hz = 1e6   # 1 МГц допуск
        if abs(nearest_hz - freq_hz) > threshold_hz:
            return
        target_mhz = nearest_hz / 1e6
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                try:
                    if abs(float(item.text()) - target_mhz) < 0.01:
                        self.table.blockSignals(True)
                        self.table.selectRow(row)
                        self.table.blockSignals(False)
                        self.table.scrollTo(self.table.model().index(row, 0))
                        break
                except ValueError:
                    pass

    def _on_zero_span_start(self, freq_hz: float) -> None:
        self._stop_zero_span()
        sig = self._signal_by_freq(freq_hz)
        baseline = sig.amplitude_on_db if sig else -80.0
        self.zero_span_widget.clear()
        self.zero_span_widget.set_signal_info(freq_hz, baseline)
        self._spectrum_stack.setCurrentIndex(1)
        from copy import copy
        self._zs_worker = ZeroSpanWorker(self.ctrl, copy(self.cfg), freq_hz)
        self._zs_worker.amplitude_updated.connect(self.zero_span_widget.add_point)
        self._zs_worker.amplitude_updated.connect(self._audio.set_amplitude)
        self._zs_worker.start()
        self._audio.start()
        self.expert_panel.enable_remeasure(False)

    def _on_zero_span_stop(self) -> None:
        self._stop_zero_span()
        self._spectrum_stack.setCurrentIndex(0)
        self.expert_panel.set_zero_span_active(False)
        if self.current_step == "idle":
            self.expert_panel.enable_remeasure(True)

    def _stop_zero_span(self) -> None:
        if self._zs_worker is not None:
            self._zs_worker.stop()
            self._zs_worker = None
        self._audio.stop()

    def _signal_by_freq(self, freq_hz: float):
        signals = self.wf.signals if self.wf and hasattr(self.wf, "signals") else []
        if not signals:
            return None
        return min(signals, key=lambda s: abs(s.frequency_hz - freq_hz))

    def _on_expert_signal_modified(self, idx: int) -> None:
        signals = self.wf.signals if self.wf and hasattr(self.wf, "signals") else []
        if signals:
            self._update_table_from_signals(signals)
            self.plot.plot_signals(signals)
            if 0 <= idx < len(signals):
                sig = signals[idx]
                self.plot.set_highlight(sig.frequency_hz / 1e6)

    def _on_graph_click(self, freq_mhz: float):
        if not self.wf or not hasattr(self.wf, "signals") or not self.wf.signals:
            return

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
            self.expert_panel.clear_signal()
            return

        self.plot.set_highlight(nearest_sig.frequency_hz / 1e6)
        self.expert_panel.set_signal(nearest_sig, nearest_i)

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

    # ------------------------------------------------------------------
    # Работа с архивом NPZ
    # ------------------------------------------------------------------

    def _load_npz(self, title: str):
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", "NumPy Archive (*.npz)"
        )
        if not path:
            return None
        try:
            return np.load(path, allow_pickle=True)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{e}")
            return None

    @staticmethod
    def _npz_to_spectra(data):
        rbw = float(data['cfg_rbw_hz'])
        ts  = float(data['timestamp'])
        freqs = data['frequencies_hz']
        on = Spectrum(frequencies_hz=freqs, amplitudes_db=data['amplitudes_on_db'],
                      rbw_hz=rbw, timestamp=ts)
        off = Spectrum(frequencies_hz=freqs, amplitudes_db=data['amplitudes_off_db'],
                       rbw_hz=rbw, timestamp=ts)
        diff = data['diff_db']
        return on, off, diff

    @staticmethod
    def _npz_to_signals(data):
        if 'signal_frequencies_hz' not in data:
            return []
        rbw = float(data['cfg_rbw_hz'])
        signals = []
        for i in range(len(data['signal_frequencies_hz'])):
            def _bool_or_none(val):
                return None if np.isnan(float(val)) else bool(val)

            sig = PEMINSignal(
                frequency_hz=float(data['signal_frequencies_hz'][i]),
                amplitude_diff_db=float(data['signal_diff_db'][i]),
                amplitude_on_db=float(data['signal_on_db'][i]),
                amplitude_off_db=float(data['signal_off_db'][i]),
                rbw_hz=rbw,
                verified_1=_bool_or_none(data['signal_verified_1'][i]),
                verified_2=_bool_or_none(data['signal_verified_2'][i]),
                status_color=str(data['signal_status'][i]),
            )
            signals.append(sig)
        return signals

    def _load_measurement(self):
        data = self._load_npz("Загрузить измерение")
        if data is None:
            return

        on, off, diff = self._npz_to_spectra(data)
        signals = self._npz_to_signals(data)

        self.wf = types.SimpleNamespace(signals=signals)
        self._plot_data(on, off, diff)

        self.act_save.setEnabled(bool(signals))
        self.act_export_spectrum.setEnabled(True)
        self.plot.enable_live_overlay_btn(True)

        from datetime import datetime as dt
        ts = dt.fromtimestamp(on.timestamp).strftime("%d.%m.%Y %H:%M:%S")
        self.lbl_instruction.setText(
            f"<b>📂 Архив загружен</b><br>"
            f"<span style='color:#aaa'>Время измерения: {ts}<br>"
            f"Сигналов: {len(signals)}</span>"
        )

    def _compare_sessions(self):
        data_a = self._load_npz("Загрузить первое измерение (A)")
        if data_a is None:
            return
        data_b = self._load_npz("Загрузить второе измерение (B)")
        if data_b is None:
            return

        on_a, off_a, diff_a = self._npz_to_spectra(data_a)
        on_b, off_b, diff_b = self._npz_to_spectra(data_b)

        self.plot.clear()
        self.table.setRowCount(0)
        self.wf = None

        f_a = on_a.frequencies_hz / 1e6
        f_b = on_b.frequencies_hz / 1e6

        self.plot.add("ON — сессия A",   f_a, on_a.amplitudes_db,  "#FFC107", width=1)
        self.plot.add("ON — сессия B",   f_b, on_b.amplitudes_db,  "#00BCD4", width=1)
        self.plot.add("Δ — сессия A",    f_a, diff_a,              "#FF5722", width=2)
        self.plot.add("Δ — сессия B",    f_b, diff_b,              "#AB47BC", width=2)

        x_min = min(float(f_a.min()), float(f_b.min()))
        x_max = max(float(f_a.max()), float(f_b.max()))
        self.plot.set_freq_range(x_min, x_max)
        self.plot.set_threshold(self.cfg.threshold_db, [x_min, x_max])
        self.plot.reset_zoom()

        self._last_on = on_a
        self._last_off = off_a
        self._last_diff = diff_a
        self.act_export_spectrum.setEnabled(True)
        self.act_save.setEnabled(False)

        from datetime import datetime as dt
        ts_a = dt.fromtimestamp(on_a.timestamp).strftime("%d.%m.%Y %H:%M")
        ts_b = dt.fromtimestamp(on_b.timestamp).strftime("%d.%m.%Y %H:%M")
        self.lbl_instruction.setText(
            f"<b>⚖ Режим сравнения</b><br>"
            f"<span style='color:#FFC107'>■</span> Сессия A: {ts_a}<br>"
            f"<span style='color:#00BCD4'>■</span> Сессия B: {ts_b}"
        )

    def _refresh_markers(self):
        if self.wf and hasattr(self.wf, "signals"):
            self.plot.plot_signals(self.wf.signals)
            self._update_table_from_signals(self.wf.signals)

    def _on_action_needed(self, title, instruction, btn_text):
        self.current_step = "waiting"
        self._current_action_title = title

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
        self.btn_stop.setEnabled(True)

        if "ЗАВЕРШЕНА" in title or "ЗАВЕРШЕНО" in title:
            self.btn_action.setStyleSheet("""
                QPushButton { background-color: #4CAF50; color: white; font-weight: bold;
                              padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
                QPushButton:hover { background-color: #388E3C; }
            """)
            self.act_save.setEnabled(True)
            self.act_export_spectrum.setEnabled(self._last_on is not None)
        else:
            self.btn_action.setStyleSheet("""
                QPushButton { background-color: #FF9800; color: white; font-weight: bold;
                              padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
                QPushButton:hover { background-color: #F57C00; }
            """)

        if self.wf and hasattr(self.wf, "signals"):
            self._update_table_only()

    def _do_ui_reset(self):
        # Отключаем finished_signal до сброса — иначе он переопределит текст кнопки
        if self.thread is not None:
            try:
                self.thread.finished_signal.disconnect(self._on_thread_finished)
            except Exception:
                pass

        self.current_step = "idle"
        self.wf = None
        self.thread = None
        self._resetting = False

        # Отключаем обновление диапазона частот live-режима
        try:
            self.spin_start_freq.valueChanged.disconnect(self._on_live_freq_range_changed)
        except Exception:
            pass
        try:
            self.spin_stop_freq.valueChanged.disconnect(self._on_live_freq_range_changed)
        except Exception:
            pass

        self._stop_overlay()
        self._stop_panorama_preview()
        self.plot.enable_live_overlay_btn(False)
        self.plot.clear()
        self.table.setRowCount(0)
        self.prog.setValue(0)
        self._stop_zero_span()
        self._stop_live()
        self.live_widget.clear()
        self._spectrum_stack.setCurrentIndex(0)
        self.expert_panel.clear_signal()
        self.expert_panel.set_zero_span_active(False)
        self.expert_panel.enable_remeasure(False)

        self.lbl_instruction.setText("Подключите SDR для начала работы.")
        self.lbl_instruction.setStyleSheet(
            "color: #e0e0e0; font-size: 13px; padding: 10px;"
            "background-color: #2b2b2b; border: 1px solid #444; border-radius: 4px;"
        )
        self._set_scan_mode(self.scan_mode)   # восстанавливает текст кнопки
        self.btn_action.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; font-weight: bold;
                          padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled { background-color: #444; color: #888; }
        """)
        self.btn_action.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.act_save.setEnabled(False)
        self.act_export_spectrum.setEnabled(False)
        self._last_on = None
        self._last_off = None
        self._last_diff = None
        self._set_settings_enabled(True)

    # ------------------------------------------------------------------
    # Live overlay в панораме
    # ------------------------------------------------------------------

    def _on_panorama_live_toggled(self, checked: bool) -> None:
        if checked:
            if not self.ctrl or not self.ctrl.is_connected:
                from PyQt6.QtWidgets import QMessageBox as _MB
                _MB.warning(self, "Нет подключения",
                            "SDR не подключён — live overlay недоступен.")
                self.plot.btn_live_overlay.blockSignals(True)
                self.plot.btn_live_overlay.setChecked(False)
                self.plot.btn_live_overlay.blockSignals(False)
                return

            from copy import copy as _copy
            ov_cfg = _copy(self.cfg)
            ov_cfg.fft_size = 2048
            ov_cfg.averaging_count = 1
            ov_cfg.use_max_hold = False

            # Ограничиваем диапазон overlay текущей областью вида для быстрого обновления
            view_x = self.plot.plot.viewRange()[0]
            if view_x[0] is not None and view_x[1] is not None:
                ov_start = max(float(view_x[0]) * 1e6, self.cfg.start_freq_hz)
                ov_stop  = min(float(view_x[1]) * 1e6, self.cfg.stop_freq_hz)
                if ov_start < ov_stop:
                    ov_cfg.start_freq_hz = ov_start
                    ov_cfg.stop_freq_hz  = ov_stop

            self._overlay_worker = LiveWorker(self.ctrl, ov_cfg)
            Q = Qt.ConnectionType.QueuedConnection
            self._overlay_worker.spectrum_ready.connect(
                lambda f, a: self.plot.update_live_overlay(f / 1e6, a), Q
            )
            self._overlay_worker.error.connect(
                lambda e: self._on_overlay_error(e), Q
            )
            self._overlay_worker.start()

            # Обновляем конфиг overlay при зуме/пане
            vb = self.plot.plot.getPlotItem().getViewBox()
            vb.sigXRangeChanged.connect(self._update_overlay_range)
        else:
            self._stop_overlay()

    def _on_overlay_error(self, err: str) -> None:
        self._stop_overlay()
        self.plot.btn_live_overlay.blockSignals(True)
        self.plot.btn_live_overlay.setChecked(False)
        self.plot.btn_live_overlay.blockSignals(False)
        QMessageBox.warning(self, "Live overlay", f"Ошибка получения спектра:\n{err}")

    def _update_overlay_range(self) -> None:
        """Обновляет диапазон overlay при изменении вида (зум/пан)."""
        if self._overlay_worker is None:
            return
        view_x = self.plot.plot.viewRange()[0]
        if view_x[0] is None or view_x[1] is None:
            return
        from copy import copy as _copy
        ov_cfg = _copy(self.cfg)
        ov_cfg.fft_size = 2048
        ov_cfg.averaging_count = 1
        ov_cfg.use_max_hold = False
        ov_start = max(float(view_x[0]) * 1e6, self.cfg.start_freq_hz)
        ov_stop  = min(float(view_x[1]) * 1e6, self.cfg.stop_freq_hz)
        if ov_start < ov_stop:
            ov_cfg.start_freq_hz = ov_start
            ov_cfg.stop_freq_hz  = ov_stop
            self._overlay_worker.update_config(ov_cfg)

    def _stop_overlay(self) -> None:
        if self._overlay_worker is not None:
            self._overlay_worker.stop()
            self._overlay_worker.wait(2000)
            self._overlay_worker = None
        # Отключаем сигнал зума если был подключён
        try:
            vb = self.plot.plot.getPlotItem().getViewBox()
            vb.sigXRangeChanged.disconnect(self._update_overlay_range)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Метки из live-режима и панорамы
    # ------------------------------------------------------------------

    def _on_live_freq_marked(self, freq_mhz: float) -> None:
        freq_hz = freq_mhz * 1e6
        if not any(abs(f - freq_hz) < 100e3 for f in self._bookmark_freqs_hz):
            self._bookmark_freqs_hz.append(freq_hz)
        self._refresh_bookmark_table()

    def _on_panorama_freq_marked(self, freq_mhz: float) -> None:
        """Пользователь поставил метку на панораме — сохраняем как закладку."""
        freq_hz = freq_mhz * 1e6
        if not any(abs(f - freq_hz) < 100e3 for f in self._bookmark_freqs_hz):
            self._bookmark_freqs_hz.append(freq_hz)
        self._refresh_bookmark_table()

    def _refresh_bookmark_table(self) -> None:
        if self.wf and hasattr(self.wf, "signals") and self.wf.signals:
            return
        bookmarks = [
            PEMINSignal(
                frequency_hz=f,
                amplitude_diff_db=0.0,
                amplitude_on_db=0.0,
                amplitude_off_db=0.0,
                rbw_hz=0.0,
                detection_method="bookmark",
            )
            for f in self._bookmark_freqs_hz
        ]
        self._update_table_from_signals(bookmarks)

    def _on_thread_finished(self):
        # Вызывается только при нормальном завершении (при сбросе — отключается в _do_ui_reset)
        self.btn_stop.setEnabled(True)
        self.current_step = "idle"
        self._set_settings_enabled(True)
        self.btn_action.setText("НОВЫЙ ПОИСК")
        self.btn_action.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; font-weight: bold;
                          padding: 12px; border-radius: 4px; font-size: 14px; border: none; }
            QPushButton:hover { background-color: #1976D2; }
        """)
        self.plot.enable_live_overlay_btn(True)
        self.expert_panel.enable_remeasure(True)

    def _plot_data(self, on, off, diff):
        self._last_on = on
        self._last_off = off
        self._last_diff = diff
        f_mhz = on.frequencies_hz / 1e6
        x_min, x_max = float(f_mhz.min()), float(f_mhz.max())

        self.plot.clear()
        self.plot.set_freq_range(x_min, x_max)
        self.plot.add("ON (Test)", f_mhz, on.amplitudes_db, "y")
        self.plot.add("OFF (Noise)", f_mhz, off.amplitudes_db, "b")
        self.plot.add("Difference", f_mhz, diff, "r", width=2)
        self.plot.set_threshold(self.cfg.threshold_db, [x_min, x_max])

        if self.wf and hasattr(self.wf, "signals"):
            self._update_table_from_signals(self.wf.signals)
            self.plot.plot_signals(self.wf.signals)

        self.plot.reset_zoom()

    def _update_table_only(self):
        if self.wf and hasattr(self.wf, "signals"):
            self._update_table_from_signals(self.wf.signals)

    # ------------------------------------------------------------------
    # Таблица результатов
    # ------------------------------------------------------------------

    def _update_table_from_signals(self, signals):
        COLOR_WAIT    = "#9E9E9E"
        COLOR_SUCCESS = "#66BB6A"
        COLOR_FAIL_V1 = "#EF5350"
        COLOR_EXTERNAL = "#42A5F5"
        COLOR_WARN    = "#FFCA28"

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
            item_freq.setData(Qt.ItemDataRole.UserRole, i)

            if s.detection_method == "bookmark" and s.verified_1 is None and s.amplitude_on_db == 0.0:
                item_harm   = QTableWidgetItem("—")
                item_diff   = QTableWidgetItem("—")
                item_on     = QTableWidgetItem("—")
                item_off    = QTableWidgetItem("—")
                item_status = QTableWidgetItem("📌 Потенциальный")
                item_status.setForeground(QColor(COLOR_WARN))
                # Оранжевый фон для bookmark-сигналов
                for col, item in enumerate([item_freq, item_diff, item_on,
                                            item_off, item_harm, item_status]):
                    item.setBackground(QColor("#FF9800"))
                    self.table.setItem(i, col, item)
                continue

            item_diff = QTableWidgetItem(f"{s.amplitude_diff_db:.1f}")
            item_on   = QTableWidgetItem(f"{s.amplitude_on_db:.1f}")
            item_off  = QTableWidgetItem(f"{s.amplitude_off_db:.1f}")

            if s.detection_method == "harmonic_search":
                if s.harmonic_count > 0:
                    harm_freqs = ", ".join(
                        f"{f / 1e6:.3f}" for f in s.harmonic_frequencies_hz
                    )
                    harm_text = f"{s.harmonic_count}  [{harm_freqs} МГц]"
                else:
                    harm_text = "—"
                item_harm = QTableWidgetItem(harm_text)
            else:
                item_harm = QTableWidgetItem("—")

            if s.detection_method == "harmonic_search":
                if s.status_color == "green":
                    status_text = f"✅ ПЭМИН ({s.harmonic_count} гарм.)"
                    color_hex = COLOR_SUCCESS
                elif s.status_color == "yellow":
                    status_text = f"⏳ Неопределённо ({s.harmonic_count} гарм.)"
                    color_hex = COLOR_WARN
                else:
                    status_text = "❌ Гармоник нет"
                    color_hex = COLOR_FAIL_V1
            else:
                color_map = {
                    "yellow": (COLOR_WARN,     "⏳ В1 OK"),
                    "green":  (COLOR_SUCCESS,  "✅ ПЭМИН"),
                    "red":    (COLOR_FAIL_V1,  "❌ Брак (В1)"),
                    "blue":   (COLOR_EXTERNAL, "〇 Внешний / Двойной брак"),
                }
                v1 = s.verified_1
                v2 = s.verified_2
                if v1 is None and v2 is None:
                    status_text = "⏳ Ожидание"
                    color_hex = COLOR_WAIT
                elif v1 is not None and v2 is None:
                    if v1:
                        status_text = "⏳ В1 OK"
                        color_hex = COLOR_WARN
                    else:
                        status_text = "❌ Брак (В1)"
                        color_hex = COLOR_FAIL_V1
                else:
                    color_hex, status_text = color_map.get(
                        s.status_color, (COLOR_WAIT, "—")
                    )
                    if s.status_color == "blue":
                        status_text = "〇 Внешний (В2)" if (v1 and not v2) else "〇 Двойной брак"

            if s.detection_method == "bookmark":
                status_text = "📌 " + status_text

            item_status = QTableWidgetItem(status_text)
            item_status.setForeground(QColor(color_hex))

            self.table.setItem(i, 0, item_freq)
            self.table.setItem(i, 1, item_diff)
            self.table.setItem(i, 2, item_on)
            self.table.setItem(i, 3, item_off)
            self.table.setItem(i, 4, item_harm)
            self.table.setItem(i, 5, item_status)

        self.table.setUpdatesEnabled(True)
        self.table.setSortingEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
