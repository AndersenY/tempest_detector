import sys
import csv
import types
import numpy as np
import pyqtgraph as pg
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTableWidget, QTableWidgetItem, QLabel,
                             QProgressBar, QMessageBox, QGroupBox, QHeaderView,
                             QApplication, QFileDialog, QDoubleSpinBox, QSpinBox,
                             QCheckBox, QStackedWidget, QComboBox,
                             QStyledItemDelegate, QAbstractItemDelegate)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtGui import QColor, QAction, QActionGroup
from core.config import PanoramaConfig
from core.backends import BaseInstrument, RtlSdrBackend, DemoSimulator
from core.models import Spectrum, PEMINSignal
from core.methods import PanoramaDiffWorkflow, HarmonicSearchWorkflow
from core.audio_monitor import AudioMonitor
from core.zero_span import ZeroSpanWorker
from core.remote_control_server import RemoteControlServer
from gui.spectrum_widget import SpectrumPlotWidget, _marker_color
from gui.expert_panel import ExpertPanel
from gui.zero_span_widget import ZeroSpanWidget
from gui.live_widget import LiveWidget
from gui.theme import DARK, LIGHT
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


class _StatusDelegate(QStyledItemDelegate):
    """Делегат для колонки «Статус»: редактирование через выпадающий список."""

    _OPTIONS = [
        ("✅ ПЭМИН",         "#66BB6A", "green"),
        ("❌ Брак (В1)",      "#EF5350", "red"),
        ("〇 Внешний (В2)",  "#42A5F5", "blue"),
        ("〇 Двойной брак",  "#42A5F5", "blue"),
        ("⏳ В1 OK",          "#FFCA28", "yellow"),
        ("⏳ Ожидание",       "#9E9E9E", "yellow"),
        ("📌 Потенциальный",  "#FFCA28", "yellow"),
        ("❌ Гармоник нет",   "#EF5350", "red"),
    ]

    # Цвета по умолчанию (тёмная тема); обновляются через set_theme()
    _bg       = "#2b2b2b"
    _fg       = "#e0e0e0"
    _border   = "#555555"
    _sel_bg   = "#1565C0"   # синий, хорошо виден на тёмном и светлом
    _sel_fg   = "#ffffff"

    def set_theme(self, t: dict) -> None:
        self._bg     = t["bg_widget"]
        self._fg     = t["text"]
        self._border = t["border_input"]
        if t["name"] == "dark":
            self._sel_bg = "#1E88E5"   # яркий синий — хорошо виден на тёмном фоне
            self._sel_fg = "#ffffff"
        else:
            self._sel_bg = "#1565C0"   # насыщенный синий на светлом фоне
            self._sel_fg = "#ffffff"

    @classmethod
    def color_for(cls, text: str) -> str:
        for label, hex_color, _ in cls._OPTIONS:
            if label in text:
                return hex_color
        return "#9E9E9E"

    @classmethod
    def key_for(cls, text: str) -> str:
        for label, _, key in cls._OPTIONS:
            if label in text:
                return key
        return "yellow"

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems([t for t, _, _ in self._OPTIONS])
        combo.setStyleSheet(
            f"QComboBox {{"
            f" background-color: {self._bg}; color: {self._fg};"
            f" border: 1px solid {self._border}; padding: 2px 6px; }}"
            f" QComboBox::drop-down {{ border: none; }}"
            f" QComboBox QAbstractItemView {{"
            f" background-color: {self._bg}; color: {self._fg};"
            f" border: 1px solid {self._border}; outline: none; }}"
            f" QComboBox QAbstractItemView::item {{"
            f" padding: 4px 6px; color: {self._fg}; }}"
            f" QComboBox QAbstractItemView::item:selected {{"
            f" background-color: {self._sel_bg}; color: {self._sel_fg}; }}"
            f" QComboBox QAbstractItemView::item:hover {{"
            f" background-color: {self._sel_bg}; color: {self._sel_fg}; }}"
        )
        combo.activated.connect(
            lambda _: (self.commitData.emit(combo),
                       self.closeEditor.emit(
                           combo, QAbstractItemDelegate.EndEditHint.NoHint))
        )
        # Открываем выпадающий список сразу после показа редактора (убирает лишний клик)
        QTimer.singleShot(0, combo.showPopup)
        return combo

    def setEditorData(self, editor, index):
        current = index.data(Qt.ItemDataRole.DisplayRole) or ""
        for i, (text, _, _) in enumerate(self._OPTIONS):
            if text in current:
                editor.setCurrentIndex(i)
                return
        editor.setCurrentIndex(0)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.DisplayRole)


class MainWindow(QMainWindow):
    _remote_count_signal = pyqtSignal(int)   # потокобезопасное обновление UI

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

        self._theme = DARK
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
        self._panorama_preview_worker: LiveWorker | None = None
        self._bookmark_freqs_hz: list[float] = []   # частоты (Гц), отмеченные в live

        self.scan_mode = "full"   # "full"|"quick"|"harmonic"|"simulator"|"demo"

        self._remote_server = RemoteControlServer()
        self._remote_server.on_client_count_changed = self._on_remote_client_count
        self._remote_count_signal.connect(self._update_remote_status)
        self._remote_server.start()

        self._init_ui()
        self._setup_menu_bar()
        self._update_remote_status(0)
        self.apply_theme(DARK)

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

        # ── Вид ───────────────────────────────────────────────────────
        menu_view = mb.addMenu("Вид")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)

        self.act_theme_dark = QAction("Тёмная тема", self)
        self.act_theme_dark.setCheckable(True)
        self.act_theme_dark.setChecked(True)
        self.act_theme_dark.triggered.connect(lambda: self.apply_theme(DARK))
        theme_group.addAction(self.act_theme_dark)
        menu_view.addAction(self.act_theme_dark)

        self.act_theme_light = QAction("Светлая тема", self)
        self.act_theme_light.setCheckable(True)
        self.act_theme_light.triggered.connect(lambda: self.apply_theme(LIGHT))
        theme_group.addAction(self.act_theme_light)
        menu_view.addAction(self.act_theme_light)

    def _set_scan_mode(self, mode: str):
        # Смена режима во время активной сессии → сбрасываем всё.
        # scan_mode устанавливаем ДО вызова _reset_to_start, чтобы _do_ui_reset
        # вызвал _set_scan_mode с уже новым режимом и корректно обновил кнопку.
        if self.current_step != "idle" and mode != self.scan_mode:
            self.scan_mode = mode
            self._reset_to_start()
            return

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
        # Колонка «Гармоники» — только для harmonic-режима
        self.table.setColumnHidden(4, mode != "harmonic")

    # ------------------------------------------------------------------
    # Тема оформления
    # ------------------------------------------------------------------

    def apply_theme(self, t: dict) -> None:
        self._theme = t
        self._status_delegate.set_theme(t)

        # Главное окно + QGroupBox глобально
        self.setStyleSheet(
            f"QMainWindow {{ background-color: {t['bg_window']}; }}"
            f" QGroupBox {{ font-weight: bold; border: 1px solid {t['border']};"
            f" border-radius: 5px; margin-top: 10px; padding-top: 10px; color: {t['text']}; }}"
            f" QGroupBox::title {{ subcontrol-origin: margin; left: 10px;"
            f" padding: 0 5px 0 5px; }}"
        )

        # Меню
        self.menuBar().setStyleSheet(
            f"QMenuBar {{ background-color: {t['mb_bg']}; color: {t['mb_fg']}; }}"
            f" QMenuBar::item:selected {{ background-color: {t['mb_sel']}; }}"
            f" QMenu {{ background-color: {t['menu_bg']}; color: {t['mb_fg']};"
            f" border: 1px solid {t['menu_bdr']}; }}"
            f" QMenu::item:selected {{ background-color: {t['menu_sel']}; }}"
            f" QMenu::separator {{ height: 1px; background: {t['menu_bdr']}; margin: 3px 0; }}"
        )

        # Прогресс-бар
        self.prog.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {t['border']}; border-radius: 4px;"
            f" text-align: center; color: {t['text']}; background-color: {t['bg_progress']}; }}"
            f" QProgressBar::chunk {{ background-color: #2196F3; width: 10px; margin: 0.5px; }}"
        )

        # Кнопка сброс
        self.btn_stop.setStyleSheet(
            f"QPushButton {{ background-color: #D32F2F; color: white; font-weight: bold;"
            f" padding: 5px 15px; border-radius: 4px; }}"
            f" QPushButton:hover {{ background-color: #B71C1C; }}"
            f" QPushButton:disabled {{ background-color: {t['btn_bg']}; color: {t['text_off']}; }}"
        )

        # Таблица результатов
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {t['bg_table']};"
            f" alternate-background-color: {t['bg_table_alt']};"
            f" color: {t['text']}; gridline-color: {t['border']};"
            f" border: 1px solid {t['border']}; }}"
            f" QHeaderView::section {{ background-color: {t['bg_header']}; color: {t['text']};"
            f" padding: 4px; border: 1px solid {t['border']}; font-weight: bold; }}"
            f" QTableWidget::item:selected {{ background-color: #2196F3; color: white; }}"
        )

        # Панель инструкции
        self.lbl_instruction.setStyleSheet(
            f"color: {t['text']}; font-size: 13px; padding: 10px;"
            f" background-color: {t['bg_instruction']}; border: 1px solid {t['border']};"
            f" border-radius: 4px;"
        )

        # Панель удалённого управления
        self._remote_box.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; border: 1px solid {t['border']};"
            f" border-radius: 4px; margin-top: 8px; padding-top: 6px;"
            f" color: {t['remote_title']}; font-size: 11px; }}"
            f" QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}"
            f" QLabel {{ color: {t['text_dim']}; font-size: 11px; }}"
            f" QSpinBox, QComboBox {{ background: {t['bg_input']}; color: {t['text']};"
            f" border: 1px solid {t['border_input']}; border-radius: 3px; padding: 1px 3px; }}"
            f" QComboBox::drop-down {{ border: none; }}"
            f" QComboBox QAbstractItemView {{ background: {t['bg_widget']}; color: {t['text']};"
            f" selection-background-color: {t['mb_sel']}; }}"
        )
        self._lbl_remote_addr.setStyleSheet(
            f"color: {t['remote_addr']}; font-family: monospace;"
        )
        # restore spinbox (overridden by remote_box QSS, but keep explicit for min-width)
        self._spin_settle.setStyleSheet(
            f"QSpinBox {{ background: {t['bg_input']}; color: {t['text']};"
            f" border: 1px solid {t['border_input']};"
            f" border-radius: 3px; padding: 1px 3px; min-width: 75px; }}"
        )

        # Панель параметров
        self._settings_panel.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; border: 1px solid {t['border']};"
            f" border-radius: 5px; margin-top: 10px; padding-top: 8px; color: {t['text']}; }}"
            f" QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}"
            f" QDoubleSpinBox, QSpinBox {{ background-color: {t['bg_input']}; color: {t['text']};"
            f" border: 1px solid {t['border_input']}; border-radius: 3px;"
            f" padding: 2px 4px; min-width: 70px; }}"
            f" QLabel {{ color: {t['text_dim']}; font-size: 12px; }}"
            f" QCheckBox {{ color: {t['text_dim']}; font-size: 12px; }}"
        )
        self.spin_avg.setStyleSheet(
            f"QSpinBox {{ background-color: {t['bg_input']}; color: {t['text']};"
            f" border: 1px solid {t['border_input']}; border-radius: 3px;"
            f" padding: 2px 4px; min-width: 55px; }}"
        )

        # Кнопка действия
        self.btn_action.setStyleSheet(
            f"QPushButton {{ background-color: #2196F3; color: white; font-weight: bold;"
            f" padding: 12px; border-radius: 4px; font-size: 14px; border: none; }}"
            f" QPushButton:hover {{ background-color: #1976D2; }}"
            f" QPushButton:disabled {{ background-color: {t['btn_bg']};"
            f" color: {t['text_off']}; }}"
        )

        # Дочерние виджеты с pyqtgraph
        self.plot.apply_theme(t)
        self.live_widget.apply_theme(t)
        self.zero_span_widget.apply_theme(t)
        self.expert_panel.apply_theme(t)

    def _init_ui(self):
        w = QWidget()
        self.setCentralWidget(w)
        main_layout = QVBoxLayout(w)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Панель прогресса + стоп
        self._top_bar = QWidget()
        top_control_layout = QHBoxLayout(self._top_bar)
        top_control_layout.setContentsMargins(0, 0, 0, 0)
        top_control_layout.setSpacing(5)

        self.prog = QProgressBar()
        self.prog.setTextVisible(True)
        self.prog.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444; border-radius: 4px;
                text-align: center; color: white; background-color: #333;
            }
            QProgressBar::chunk { background-color: #2196F3; width: 10px; margin: 0.5px; }
        """)
        # Плавная анимация прогрессбара
        self._prog_anim = QPropertyAnimation(self.prog, b"value")
        self._prog_anim.setDuration(450)
        self._prog_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Таймер буферизации для полуавтоматического режима
        self._settle_timer = QTimer()
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._finish_semi_auto_resume)

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
        main_layout.addWidget(self._top_bar)

        # Панель параметров измерения
        self._settings_panel = self._create_settings_panel()
        main_layout.addWidget(self._settings_panel)

        # График спектра / Zero Span (переключаются через QStackedWidget)
        self.plot = SpectrumPlotWidget()
        self.plot.freq_clicked.connect(self._on_graph_click)
        self.plot.freq_mark_added.connect(self._on_panorama_freq_marked)
        self.zero_span_widget = ZeroSpanWidget()
        self.live_widget = LiveWidget()
        self.live_widget.freq_marked.connect(self._on_live_freq_marked)
        self.live_widget.freq_selected.connect(self._on_live_graph_freq_clicked)
        self.live_widget.marks_cleared.connect(self._on_live_marks_cleared)
        self.plot.fullscreen_toggled.connect(self._toggle_graph_fullscreen)
        self.live_widget.fullscreen_toggled.connect(self._toggle_graph_fullscreen)
        self.live_widget.view_range_changed.connect(self._on_live_view_range_changed)
        self.live_widget.stop_requested.connect(self._on_live_stop_requested)
        self.live_widget.resume_requested.connect(self._on_live_resume_requested)
        self._spectrum_stack = QStackedWidget()
        self._spectrum_stack.addWidget(self.plot)            # index 0 — спектр
        self._spectrum_stack.addWidget(self.zero_span_widget)  # index 1 — zero span
        self._spectrum_stack.addWidget(self.live_widget)     # index 2 — прямой эфир
        main_layout.addWidget(self._spectrum_stack, 3)

        # Нижняя секция: таблица + управление
        self._bottom_widget = QWidget()
        bottom_section = QHBoxLayout(self._bottom_widget)
        bottom_section.setContentsMargins(0, 0, 0, 0)
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
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked |
            QTableWidget.EditTrigger.EditKeyPressed
        )
        self._status_delegate = _StatusDelegate(self.table)
        self.table.setItemDelegateForColumn(5, self._status_delegate)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
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

        # ── Панель удалённого управления ──────────────────────────────
        _remote_style = """
            QGroupBox { font-weight: bold; border: 1px solid #444; border-radius: 4px;
                        margin-top: 8px; padding-top: 6px; color: #90CAF9; font-size: 11px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QLabel { color: #ccc; font-size: 11px; }
            QSpinBox, QComboBox { background:#333; color:#e0e0e0; border:1px solid #555;
                                  border-radius:3px; padding:1px 3px; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background:#2b2b2b; color:#e0e0e0;
                                          selection-background-color:#444; }
        """
        self._remote_box = QGroupBox("Удалённое управление")
        remote_box = self._remote_box
        remote_box.setStyleSheet(_remote_style)
        remote_inner = QVBoxLayout(remote_box)
        remote_inner.setSpacing(5)
        remote_inner.setContentsMargins(8, 4, 8, 8)

        # Строка 1: выбор режима
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Режим:"))
        self._combo_mode = QComboBox()
        self._combo_mode.addItem("Ручной",              "manual")
        self._combo_mode.addItem("Полуавтоматический",  "semi_auto")
        self._combo_mode.addItem("Автоматический",       "auto")
        self._combo_mode.setToolTip(
            "<b>Ручной</b> — оператор включает/выключает тест вручную, клиент не нужен.<br>"
            "<b>Полуавтоматический</b> — оператор нажимает кнопки на детекторе,<br>"
            "тест включается/выключается автоматически через сеть.<br>"
            "<b>Автоматический</b> — детектор управляет всем самостоятельно,<br>"
            "участие оператора не требуется."
        )
        self._combo_mode.setMinimumWidth(155)
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._combo_mode)
        mode_row.addStretch()
        remote_inner.addLayout(mode_row)

        # Строка 2: адрес сервера
        addr_row = QHBoxLayout()
        addr_row.addWidget(QLabel("Адрес сервера:"))
        self._lbl_remote_addr = QLabel(self._remote_server.local_address)
        self._lbl_remote_addr.setStyleSheet("color:#90CAF9; font-family:monospace;")
        addr_row.addWidget(self._lbl_remote_addr)
        addr_row.addStretch()
        remote_inner.addLayout(addr_row)

        # Строка 3: статус подключений + буфер
        status_row = QHBoxLayout()
        self._lbl_remote_clients = QLabel("● Нет подключений")
        self._lbl_remote_clients.setStyleSheet("color:#888;")
        status_row.addWidget(self._lbl_remote_clients)
        status_row.addStretch()
        self._lbl_settle = QLabel("Буфер:")
        self._lbl_settle.setToolTip(
            "Пауза после команды ON/OFF перед захватом спектра.\n"
            "Позволяет сетевому трафику затихнуть до начала измерения."
        )
        status_row.addWidget(self._lbl_settle)
        self._spin_settle = QSpinBox()
        self._spin_settle.setRange(100, 5000)
        self._spin_settle.setValue(500)
        self._spin_settle.setSuffix(" мс")
        self._spin_settle.setToolTip(
            "Рекомендуется ≥500 мс при Ethernet, ≥1000 мс при WiFi."
        )
        self._spin_settle.setStyleSheet("""
            QSpinBox { background:#333; color:#e0e0e0; border:1px solid #555;
                       border-radius:3px; padding:1px 3px; min-width:75px; }
        """)
        status_row.addWidget(self._spin_settle)
        remote_inner.addLayout(status_row)
        control_layout.addWidget(remote_box)
        # ──────────────────────────────────────────────────────────────

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
        main_layout.addWidget(self._bottom_widget, 2)

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

        self.spin_start_freq.editingFinished.connect(self._clamp_freq_start)
        self.spin_start_freq.valueChanged.connect(self._clamp_freq_start)
        self.spin_stop_freq.editingFinished.connect(self._clamp_freq_stop)
        self.spin_stop_freq.valueChanged.connect(self._clamp_freq_stop)

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

        # Фиксация полосы пропускания в live-режиме (только пан, зум запрещён)
        self.chk_lock_bw = QCheckBox("Фиксировать полосу")
        self.chk_lock_bw.setChecked(True)
        self.chk_lock_bw.setToolTip(
            "В live-режиме зафиксировать ширину полосы SDR.\n"
            "Разрешён только пан. Предотвращает лаги."
        )
        layout.addWidget(self.chk_lock_bw)

        layout.addStretch(1)

        self._settings_widgets = [
            self.spin_start_freq, self.spin_stop_freq, self.spin_threshold,
            self.spin_gain, self.spin_avg, self.chk_maxhold, self.chk_lock_bw,
        ]
        return box

    _FREQ_BW_MHZ = 2.0   # аппаратная полоса RTL-SDR

    def _clamp_freq_start(self) -> None:
        start = self.spin_start_freq.value()
        stop  = self.spin_stop_freq.value()
        if self.chk_lock_bw.isChecked():
            # Полоса фиксирована: стоп всегда = старт + 2 МГц
            new_stop  = min(start + self._FREQ_BW_MHZ, self.spin_stop_freq.maximum())
            new_start = new_stop - self._FREQ_BW_MHZ
        elif start >= stop:
            # Полоса свободная: только защита от старт ≥ стоп
            new_stop  = min(start + self._FREQ_BW_MHZ, self.spin_stop_freq.maximum())
            new_start = start
        else:
            return
        self.spin_start_freq.blockSignals(True)
        self.spin_stop_freq.blockSignals(True)
        self.spin_start_freq.setValue(new_start)
        self.spin_stop_freq.setValue(new_stop)
        self.spin_start_freq.blockSignals(False)
        self.spin_stop_freq.blockSignals(False)

    def _clamp_freq_stop(self) -> None:
        start = self.spin_start_freq.value()
        stop  = self.spin_stop_freq.value()
        if self.chk_lock_bw.isChecked():
            # Полоса фиксирована: старт всегда = стоп − 2 МГц
            new_start = max(stop - self._FREQ_BW_MHZ, self.spin_start_freq.minimum())
            new_stop  = new_start + self._FREQ_BW_MHZ
        elif stop <= start:
            # Полоса свободная: только защита от стоп ≤ старт
            new_start = max(stop - self._FREQ_BW_MHZ, self.spin_start_freq.minimum())
            new_stop  = stop
        else:
            return
        self.spin_start_freq.blockSignals(True)
        self.spin_stop_freq.blockSignals(True)
        self.spin_start_freq.setValue(new_start)
        self.spin_stop_freq.setValue(new_stop)
        self.spin_start_freq.blockSignals(False)
        self.spin_stop_freq.blockSignals(False)

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
    # Полноэкранный режим графика
    # ------------------------------------------------------------------

    def _toggle_graph_fullscreen(self, fullscreen: bool) -> None:
        self._top_bar.setVisible(not fullscreen)
        self._bottom_widget.setVisible(not fullscreen)
        # Синхронизируем кнопку в обоих виджетах без повторного эмита
        for w in (self.plot, self.live_widget):
            w.btn_fullscreen.blockSignals(True)
            w.btn_fullscreen.setChecked(fullscreen)
            w.btn_fullscreen.blockSignals(False)

    # ------------------------------------------------------------------
    # Управление процессом
    # ------------------------------------------------------------------

    def _on_live_stop_requested(self) -> None:
        """Кнопка ■ на live_widget: в режиме live_preview — замораживаем граф
        (не сбрасываем данные), в других режимах — полный сброс."""
        if self.current_step == "live_preview":
            self._stop_panorama_preview()
            self.live_widget.set_live_running(False)
            self.btn_action.setText("▶  ЗАПУСТИТЬ ИЗМЕРЕНИЕ ПАНОРАМЫ")
            self.btn_action.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.lbl_instruction.setText(
                "<b>⏸ Прямой эфир остановлен</b><br>"
                "<span style='color:#aaa'>"
                "График заморожен. Изучите спектр.<br>"
                "Нажмите ▶ для возобновления, <b>▶ ЗАПУСТИТЬ ИЗМЕРЕНИЕ ПАНОРАМЫ</b> или <b>Сброс</b>.</span>"
            )
        else:
            self._reset_to_start()

    def _on_live_resume_requested(self) -> None:
        """Кнопка ▶ на live_widget: перезапускает прямой эфир."""
        if not self._apply_settings_to_cfg():
            return
        self._start_panorama_preview()

    # ------------------------------------------------------------------
    # Обработка ошибок SDR-устройства
    # ------------------------------------------------------------------

    @staticmethod
    def _is_device_lost(msg: str) -> bool:
        # LibUSBError(-4) форматируется как "<LIBUSB_ERROR_NO_DEVICE (-4): ...>"
        # LibUSBError(-9) — "<LIBUSB_ERROR_PIPE (-9): ...>"
        # read_bytes_sync кидает IOError("Error reading N bytes (-4)")
        # наш _check_device_present кидает IOError("LIBUSB_ERROR_NO_DEVICE (-4): ...")
        return (
            "LIBUSB_ERROR_NO_DEVICE" in msg
            or "LIBUSB_ERROR_PIPE" in msg
            or "(-4)" in msg
            or "(-9)" in msg
            or "Error code -4" in msg
            or "Error code -9" in msg
            or "disconnected" in msg.lower()
        )

    def _on_sdr_error(self, msg: str) -> None:
        """Единый обработчик ошибок SDR (LiveWorker, WorkflowThread, ZeroSpan).

        При физическом отключении устройства — бросает устаревший USB-дескриптор
        (без вызова rtlsdr_close, иначе segfault), сбрасывает UI и показывает
        предупреждение. Для прочих ошибок — сброс + диалог с текстом ошибки.
        """
        if self._is_device_lost(msg) and isinstance(self.ctrl, RtlSdrBackend):
            self.ctrl.abandon_handle()
        self._reset_to_start()
        if self._is_device_lost(msg):
            QMessageBox.warning(
                self,
                "Устройство отключено",
                "RTL-SDR донгл был отключён во время работы.\n\n"
                "Подключите устройство заново и нажмите Пуск.",
            )
        else:
            QMessageBox.critical(self, "Ошибка измерения", msg)

    def _reset_to_start(self):
        """Прерывает текущий процесс и возвращает программу в начальное состояние."""
        self._resetting = True
        self.btn_action.setEnabled(False)   # блокируем повторный запуск
        self._settle_timer.stop()           # отменяем буферную паузу если активна

        self._stop_panorama_preview()
        if self.wf:
            self.wf.stop()

        # Ждём завершения потока перед освобождением SDR
        # (предотвращает Segmentation fault при быстром нажатии Сброс → Старт)
        if self.thread is not None and self.thread.isRunning():
            self.thread.wait(10_000)

        self._do_ui_reset()

    def _on_control_button_clicked(self):
        if self.current_step == "idle":
            if self.scan_mode == "demo":
                self._load_measurement()
            else:
                self._connect_and_start()
        elif self.current_step == "live_preview":
            self._launch_measurement_from_preview()
            return
        else:
            # Определяем нужно ли авто-переключение теста на этом шаге
            title = self._current_action_title
            if "ФОН ИЗМЕРЕН" in title:
                self._begin_phase_transition(activate=True)
            elif "ВЕРИФИКАЦИЯ 1 ЗАВЕРШЕНА" in title:
                self._begin_phase_transition(activate=False)
            else:
                # Промежуточный шаг — просто продолжаем без команды
                if self.wf:
                    self.wf.resume()
                    self.btn_action.setEnabled(False)
                    self.lbl_instruction.setText("⏳ Выполнение измерения...")
                    self.btn_stop.setEnabled(True)

    # ------------------------------------------------------------------
    # Полуавтоматическое управление тестовым сигналом
    # ------------------------------------------------------------------

    def _should_auto_control_test(self) -> bool:
        """
        True если выбран полу- или автоматический режим И есть кому отправить команду
        (подключённые клиенты или DemoSimulator).
        """
        if self._control_mode == "manual":
            return False
        return (
            self._remote_server.client_count > 0
            or isinstance(self.ctrl, DemoSimulator)
        )

    def _begin_phase_transition(self, activate: bool) -> None:
        """
        Полуавтоматический переход (вызывается при клике кнопки).
        Отправляет команду теста, выдерживает буфер, затем возобновляет workflow.
        В ручном режиме — просто возобновляет немедленно.
        """
        if self._should_auto_control_test():
            self._on_test_activate(activate)
            settle_ms = self._spin_settle.value()
            label = "ВКЛ" if activate else "ВЫКЛ"
            self.btn_action.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.lbl_instruction.setText(
                f"<b>⏳ Тест {label} — стабилизация {settle_ms} мс...</b><br>"
                "<span style='color:#aaa'>Сетевой трафик затихает перед захватом спектра.</span>"
            )
            self._settle_timer.start(settle_ms)
        else:
            # Ручной режим — команды не посылаем, продолжаем немедленно
            self._finish_semi_auto_resume()

    def _finish_semi_auto_resume(self) -> None:
        """Вызывается таймером после буферной паузы — возобновляет workflow."""
        if self.wf:
            self.wf.resume()
        self.btn_action.setEnabled(False)
        self.lbl_instruction.setText("⏳ Выполнение измерения...")
        self.btn_stop.setEnabled(True)

    # ------------------------------------------------------------------

    def _connect_and_start(self):
        if not self._apply_settings_to_cfg():
            return
        self.cfg.skip_verification = (self.scan_mode == "quick")

        if self.scan_mode == "simulator":
            self._start_simulator()
            return

        try:
            # Если устройство уже открыто — только переконфигурируем.
            # close() → open() в librtlsdr вызывает повреждение кучи (malloc corruption),
            # потому что внутренние USB-потоки не успевают завершиться.
            if isinstance(self.ctrl, RtlSdrBackend) and self.ctrl.is_connected:
                try:
                    self.ctrl.configure(self.cfg)
                except Exception:
                    # Устройство было перевоткнуто: дескриптор устарел.
                    # abandon_handle() сбрасывает dev_p без вызова rtlsdr_close(),
                    # иначе librtlsdr падает с segfault при "Reattaching kernel driver".
                    self.ctrl.abandon_handle()
                    self.ctrl = RtlSdrBackend()
                    self.ctrl.connect()
                    self.ctrl.configure(self.cfg)
            else:
                try:
                    self.ctrl.close()
                except Exception:
                    pass
                self.ctrl = RtlSdrBackend()
                self.ctrl.connect()
                self.ctrl.configure(self.cfg)
            self._start_panorama_preview()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка подключения", str(e))

    def _on_preview_settings_changed(self) -> None:
        """Обновляет live preview при изменении любого параметра во время предпросмотра."""
        if self.current_step != "live_preview" or self._panorama_preview_worker is None:
            return
        start_hz = self.spin_start_freq.value() * 1e6
        stop_hz  = self.spin_stop_freq.value() * 1e6
        if stop_hz <= start_hz + 100e3:
            return
        from copy import copy as _copy
        cfg = _copy(self.cfg)
        cfg.start_freq_hz = start_hz
        cfg.stop_freq_hz  = stop_hz
        cfg.sdr_gain_db     = self.spin_gain.value()
        cfg.fft_size        = 8192
        cfg.averaging_count = 1
        cfg.use_max_hold    = False
        _LIVE_BW = 2_000_000
        if self.chk_lock_bw.isChecked():
            sender = self.sender()
            if sender is self.spin_start_freq:
                # пользователь изменил начало — сохраняем полосу, двигаем конец
                cfg.stop_freq_hz  = min(1750e6, cfg.start_freq_hz + _LIVE_BW)
                cfg.start_freq_hz = cfg.stop_freq_hz - _LIVE_BW
            elif sender is self.spin_stop_freq:
                # пользователь изменил конец — сохраняем полосу, двигаем начало
                cfg.start_freq_hz = max(24e6, cfg.stop_freq_hz - _LIVE_BW)
                cfg.stop_freq_hz  = cfg.start_freq_hz + _LIVE_BW
            else:
                # галка или другой виджет — центрируем окно 2 МГц
                center = (cfg.start_freq_hz + cfg.stop_freq_hz) / 2
                cfg.start_freq_hz = max(24e6,   center - _LIVE_BW / 2)
                cfg.stop_freq_hz  = min(1750e6, center + _LIVE_BW / 2)
            # синхронизируем спиннеры с реальным диапазоном SDR
            self.spin_start_freq.blockSignals(True)
            self.spin_stop_freq.blockSignals(True)
            self.spin_start_freq.setValue(cfg.start_freq_hz / 1e6)
            self.spin_stop_freq.setValue(cfg.stop_freq_hz / 1e6)
            self.spin_start_freq.blockSignals(False)
            self.spin_stop_freq.blockSignals(False)
        bw_mhz = (cfg.stop_freq_hz - cfg.start_freq_hz) / 1e6
        self.live_widget.set_follow_mode(bw_mhz)
        self.live_widget.set_span_lock(bw_mhz if self.chk_lock_bw.isChecked() else None)
        self._panorama_preview_worker.update_config(cfg)
        vb = self.live_widget._pw.getPlotItem().getViewBox()
        self.live_widget._snap_in_progress = True
        vb.setXRange(cfg.start_freq_hz / 1e6, cfg.stop_freq_hz / 1e6, padding=0)
        self.live_widget._snap_in_progress = False
        self.live_widget._x_initialized = True

    def _sync_live_marks(self) -> None:
        """Синхронизирует метки на live_widget с _bookmark_freqs_hz."""
        self.live_widget.set_marks([f / 1e6 for f in self._bookmark_freqs_hz])

    def _on_live_view_range_changed(self, start_mhz: float, stop_mhz: float) -> None:
        """Оператор сдвинул live-вид — ретюним SDR и обновляем спиннеры."""
        if self.current_step != "live_preview" or self._panorama_preview_worker is None:
            return
        from copy import copy as _copy
        cfg = _copy(self.cfg)
        _LIVE_BW = 2_000_000
        if self.chk_lock_bw.isChecked():
            # Всегда 2 МГц по центру вида — без sweep и лагов
            center_hz = (start_mhz + stop_mhz) / 2 * 1e6
            cfg.start_freq_hz = max(24e6,   center_hz - _LIVE_BW / 2)
            cfg.stop_freq_hz  = min(1750e6, center_hz + _LIVE_BW / 2)
            # Спиннеры показывают реальный диапазон SDR, а не диапазон вида
            spin_start = cfg.start_freq_hz / 1e6
            spin_stop  = cfg.stop_freq_hz  / 1e6
        else:
            span_hz = (stop_mhz - start_mhz) * 1e6
            cfg.start_freq_hz = max(24e6,   start_mhz * 1e6 - span_hz * 0.05)
            cfg.stop_freq_hz  = min(1750e6, stop_mhz  * 1e6 + span_hz * 0.05)
            spin_start = start_mhz
            spin_stop  = stop_mhz
        # Обновляем спиннеры без срабатывания _on_preview_settings_changed
        self.spin_start_freq.blockSignals(True)
        self.spin_stop_freq.blockSignals(True)
        self.spin_start_freq.setValue(spin_start)
        self.spin_stop_freq.setValue(spin_stop)
        self.spin_start_freq.blockSignals(False)
        self.spin_stop_freq.blockSignals(False)
        cfg.sdr_gain_db     = self.spin_gain.value()
        cfg.fft_size        = 8192
        cfg.averaging_count = 1
        cfg.use_max_hold    = False
        self._panorama_preview_worker.update_config(cfg)

    def _on_table_context_menu(self, pos) -> None:
        """Правый клик по строке — удалить метку (доступно в preview, idle и ЭТАП 1)."""
        phase1_waiting = (
            self.current_step == "waiting" and
            "ФОН ИЗМЕРЕН" in self._current_action_title
        )
        if self.current_step not in ("live_preview", "idle") and not phase1_waiting:
            return
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        freq_item = self.table.item(row, 0)
        if freq_item is None:
            return
        try:
            freq_hz = float(freq_item.text()) * 1e6
        except ValueError:
            return

        # Проверяем, что строка — метка (до или после измерения)
        is_bookmark = any(abs(f - freq_hz) < 100e3 for f in self._bookmark_freqs_hz)
        if not is_bookmark and self.wf and hasattr(self.wf, "signals"):
            signals = self.wf.signals
            if 0 <= row < len(signals):
                is_bookmark = (signals[row].detection_method == "bookmark")
        if not is_bookmark:
            return

        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        act_del = menu.addAction("🗑  Удалить метку")
        if menu.exec(self.table.viewport().mapToGlobal(pos)) == act_del:
            self._delete_bookmark(freq_hz)

    # ------------------------------------------------------------------
    # Редактирование таблицы
    # ------------------------------------------------------------------

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        row = item.row()
        col = item.column()
        text = item.text().strip()

        signals = None
        if self.wf and hasattr(self.wf, "signals") and self.wf.signals:
            signals = self.wf.signals
        if signals is None or row >= len(signals):
            return

        s = signals[row]
        try:
            if col == 0:
                s.frequency_hz = float(text) * 1e6
            elif col == 1:
                s.amplitude_diff_db = float(text)
            elif col == 2:
                s.amplitude_on_db = float(text)
            elif col == 3:
                s.amplitude_off_db = float(text)
            elif col == 5:
                color_hex = _StatusDelegate.color_for(text)
                self.table.blockSignals(True)
                item.setForeground(QColor(color_hex))
                self.table.blockSignals(False)
                s.status_color = _StatusDelegate.key_for(text)
        except (ValueError, TypeError):
            pass

    def _delete_bookmark(self, freq_hz: float) -> None:
        self._bookmark_freqs_hz = [f for f in self._bookmark_freqs_hz
                                   if abs(f - freq_hz) >= 100e3]
        self._sync_live_marks()
        self.plot.remove_panorama_mark(freq_hz / 1e6)
        self.table.clearSelection()
        self.live_widget.highlight_mark(None)
        self.plot.clear_highlight()
        # Синхронизируем список кандидатов в workflow (если идёт ЭТАП 1)
        if self.wf is not None and hasattr(self.wf, "update_bookmark_candidates"):
            self.wf.update_bookmark_candidates(self._bookmark_freqs_hz)
        # Если измерение уже выполнено — убираем метку и из wf.signals
        if self.wf and hasattr(self.wf, "signals") and self.wf.signals:
            self.wf.signals = [s for s in self.wf.signals
                               if not (s.detection_method == "bookmark" and
                                       abs(s.frequency_hz - freq_hz) < 100e3)]
            self._refresh_markers()
        else:
            self._refresh_bookmark_table()

    def _start_simulator(self):
        # Явно закрываем старый бэкенд: без этого GC вызовет rtlsdr_close() позднее,
        # что даёт "Reattached kernel driver" + usb_claim_interface error -6 при реконнекте.
        try:
            self.ctrl.close()
        except Exception:
            pass
        sim = DemoSimulator()
        sim.configure(self.cfg)
        sim._MEASURE_DELAY_S = 0.0
        self.ctrl = sim
        self._start_panorama_preview()

    def _start_panorama_preview(self) -> None:
        """Запускает live-просмотр на live_widget. Настройки остаются активными."""
        self.current_step = "live_preview"
        self.live_widget.set_live_running(True)
        # Настройки НЕ блокируются — пользователь может менять их в реальном времени
        self.btn_action.setText("▶  ЗАПУСТИТЬ ИЗМЕРЕНИЕ ПАНОРАМЫ")
        self.btn_action.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self._stop_zero_span()

        # Очищаем метки и результаты предыдущего сеанса
        self._bookmark_freqs_hz.clear()
        self.plot.clear_panorama_marks()
        self.table.setRowCount(0)

        # Показываем live_widget
        self._spectrum_stack.setCurrentIndex(2)
        self.live_widget.clear()
        self.expert_panel.set_zero_span_active(False)
        self.expert_panel.enable_remeasure(False)

        from copy import copy as _cp
        prev_cfg = _cp(self.cfg)
        prev_cfg.fft_size = 8192
        prev_cfg.averaging_count = 1
        prev_cfg.use_max_hold = False
        # При включённой фиксации полосы — ограничиваем SDR hardware-bandwidth (2 МГц),
        # чтобы всегда работал _capture_single без медленного sweep
        _LIVE_BW = 2_000_000   # _USABLE_BW из RtlSdrBackend
        if self.chk_lock_bw.isChecked():
            center = (prev_cfg.start_freq_hz + prev_cfg.stop_freq_hz) / 2
            prev_cfg.start_freq_hz = max(24e6,    center - _LIVE_BW / 2)
            prev_cfg.stop_freq_hz  = min(1750e6,  center + _LIVE_BW / 2)
        bw_mhz = (prev_cfg.stop_freq_hz - prev_cfg.start_freq_hz) / 1e6
        self.live_widget.set_follow_mode(bw_mhz)
        self.live_widget.set_span_lock(bw_mhz if self.chk_lock_bw.isChecked() else None)

        self._panorama_preview_worker = LiveWorker(self.ctrl, prev_cfg)
        Q = Qt.ConnectionType.QueuedConnection
        self._panorama_preview_worker.spectrum_ready.connect(
            self._on_panorama_preview_spectrum, Q
        )
        self._panorama_preview_worker.error.connect(self._on_sdr_error, Q)
        self._panorama_preview_worker.start()

        # Подключаем все настройки — изменение → обновление live preview.
        # editingFinished нужен для ручного ввода: valueChanged не срабатывает пока
        # промежуточное значение не войдёт в допустимый диапазон.
        for w in self._settings_widgets:
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self._on_preview_settings_changed)
                w.editingFinished.connect(self._on_preview_settings_changed)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self._on_preview_settings_changed)

        # Синхронизируем метки из предыдущих сессий
        self._sync_live_marks()
        self._refresh_bookmark_table()

        self.lbl_instruction.setText(
            "<b>📡 Прямой эфир активен</b><br>"
            "<span style='color:#aaa'>"
            "Параметры можно менять в реальном времени — спектр обновится автоматически.<br>"
            "Поставьте метки 📌 для важных частот, затем нажмите<br>"
            "<b>▶ ЗАПУСТИТЬ ИЗМЕРЕНИЕ ПАНОРАМЫ</b></span>"
        )

    def _stop_panorama_preview(self) -> None:
        # Отключаем хендлеры обновления live preview
        for w in self._settings_widgets:
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                try: w.valueChanged.disconnect(self._on_preview_settings_changed)
                except Exception: pass
                try: w.editingFinished.disconnect(self._on_preview_settings_changed)
                except Exception: pass
            elif isinstance(w, QCheckBox):
                try: w.toggled.disconnect(self._on_preview_settings_changed)
                except Exception: pass
        self.live_widget.set_follow_mode(None)
        self.live_widget.set_span_lock(None)
        if self._panorama_preview_worker is not None:
            self._panorama_preview_worker.stop()
            self._panorama_preview_worker.wait(2000)
            self._panorama_preview_worker = None

    def _on_panorama_preview_spectrum(self, freqs_hz, amps_db) -> None:
        self.live_widget.update_spectrum(freqs_hz, amps_db)

    def _launch_measurement_from_preview(self) -> None:
        """Переход от live preview к реальному измерению панорамы."""
        self._stop_panorama_preview()
        if not self._apply_settings_to_cfg():
            # Невалидные параметры — остаёмся в preview
            self._start_panorama_preview()
            return
        # Блокируем настройки только здесь — в момент запуска измерения
        self._set_settings_enabled(False)
        # Переключаем на виджет спектра
        self._spectrum_stack.setCurrentIndex(0)
        self.plot.clear()
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
        self._reset_progress()
        self._stop_zero_span()
        self._spectrum_stack.setCurrentIndex(0)
        self.expert_panel.set_zero_span_active(False)
        self.expert_panel.set_instrument(self.ctrl)
        self.expert_panel.enable_remeasure(False)

        self.plot.clear()
        # Показываем метки в таблице пока идёт фаза 1 (до обнаружения сигналов)
        self.wf = None
        self._refresh_bookmark_table()

        self.wf = self._make_workflow()
        self.wf.on_test_activate = self._on_test_activate
        # Автоматический режим: workflow сам переключает фазы без участия оператора
        if self._control_mode == "auto" and self._should_auto_control_test():
            self.wf.auto_settle_s = self._spin_settle.value() / 1000.0
        self.thread = Worker(self.wf)

        Q = Qt.ConnectionType.QueuedConnection
        self.thread.status.connect(lambda s: self.lbl_instruction.setText(s), Q)
        self.thread.progress.connect(lambda v: self._set_progress(int(v)), Q)
        self.thread.data.connect(self._plot_data, Q)
        self.thread.off_spectrum_ready.connect(self._on_off_spectrum_ready, Q)
        self.thread.action_needed.connect(self._on_action_needed, Q)
        self.thread.signals_updated.connect(self._refresh_markers, Q)
        self.thread.error.connect(self._on_sdr_error, Q)
        self.thread.finished_signal.connect(self._on_thread_finished, Q)

        self.thread.start()

    def _on_off_spectrum_ready(self, off_spec) -> None:
        """Показывает OFF-спектр сразу после захвата фона, до ON-измерения."""
        f_mhz = off_spec.frequencies_hz / 1e6
        x_min, x_max = float(f_mhz.min()), float(f_mhz.max())
        self.plot.clear()
        self.plot.set_freq_range(x_min, x_max)
        self.plot.add("OFF (фон)", f_mhz, off_spec.amplitudes_db, self._theme["curve_off"], width=0.8, theme_key="curve_off")
        self.plot.set_threshold(self.cfg.threshold_db, [x_min, x_max])
        # Восстанавливаем метки после clear() — нужны на графике во время фазы 1
        self.plot.set_panorama_marks([f / 1e6 for f in self._bookmark_freqs_hz])
        self.plot.reset_zoom()
        # Показываем кнопки меток — пользователь может добавлять частоты в ЭТАП 1
        self.plot.btn_mark_mode.setVisible(True)
        self.plot.btn_clear_marks.setVisible(True)

    def _on_table_selection_changed(self):
        if not self.table.selectedItems():
            self.plot.clear_highlight()
            self.live_widget.highlight_mark(None)
            self.expert_panel.clear_signal()
            return
        row = self.table.currentRow()
        freq_item = self.table.item(row, 0)
        if freq_item is None:
            self.plot.clear_highlight()
            self.expert_panel.clear_signal()
            return

        # В режиме предпросмотра — подсветить метку на live_widget
        if self.current_step == "live_preview":
            try:
                freq_mhz = float(freq_item.text())
                self.live_widget.highlight_mark(freq_mhz)
                vb = self.live_widget._pw.getPlotItem().getViewBox()
                x_range = vb.viewRange()[0]
                half_span = max((x_range[1] - x_range[0]) / 2, 1.0)
                vb.setXRange(freq_mhz - half_span, freq_mhz + half_span, padding=0)
            except (ValueError, AttributeError):
                pass
            return

        signals = self.wf.signals if self.wf and hasattr(self.wf, "signals") else []
        if not signals:
            # Нет сигналов — возможно идёт фаза 1 или показаны предварительные метки
            try:
                freq_mhz = float(freq_item.text())
                freq_hz  = freq_mhz * 1e6
                if any(abs(f - freq_hz) < 100e3 for f in self._bookmark_freqs_hz):
                    self.plot.set_highlight(freq_mhz)
                    self.plot.pan_to(freq_mhz)
                    return
            except ValueError:
                pass
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
        self.live_widget.highlight_mark(target_mhz)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                try:
                    if abs(float(item.text()) - target_mhz) < 0.01:
                        self.table.blockSignals(True)
                        self.table.selectRow(row)
                        self.table.blockSignals(False)
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
        self._zs_worker.error.connect(self._on_zero_span_error)
        self._zs_worker.start()
        self._audio.start()
        self.expert_panel.enable_remeasure(False)

    def _on_zero_span_stop(self) -> None:
        self._stop_zero_span()
        self._spectrum_stack.setCurrentIndex(0)
        self.expert_panel.set_zero_span_active(False)
        if self.current_step == "idle":
            self.expert_panel.enable_remeasure(True)

    def _on_zero_span_error(self, msg: str) -> None:
        self._stop_zero_span()
        if self._is_device_lost(msg):
            self._on_sdr_error(msg)
        else:
            self._spectrum_stack.setCurrentIndex(0)
            self.expert_panel.set_zero_span_active(False)
            QMessageBox.warning(self, "Zero Span", f"Ошибка измерения:\n{msg}")

    def _stop_zero_span(self) -> None:
        if self._zs_worker is not None:
            self._zs_worker.stop()
            self._zs_worker.wait(5000)  # дождаться finally-блока (restore configure)
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
            # Phase 1: сигналы ещё не обнаружены — ищем ближайшую закладку
            if not self._bookmark_freqs_hz:
                return
            freq_hz = freq_mhz * 1e6
            view_range = self.plot.plot.viewRange()[0]
            visible_span = abs(view_range[1] - view_range[0]) or 20.0
            threshold_mhz = visible_span / 20.0
            nearest_hz = min(self._bookmark_freqs_hz, key=lambda f: abs(f - freq_hz))
            if abs(nearest_hz / 1e6 - freq_mhz) > threshold_mhz:
                return
            target_mhz = nearest_hz / 1e6
            self.plot.set_highlight(target_mhz)
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item:
                    try:
                        if abs(float(item.text()) - target_mhz) < 0.01:
                            self.table.blockSignals(True)
                            self.table.selectRow(row)
                            self.table.blockSignals(False)
                            break
                    except ValueError:
                        pass
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
        on_b, _, diff_b = self._npz_to_spectra(data_b)

        self.plot.clear()
        self.table.setRowCount(0)
        self.wf = None

        f_a = on_a.frequencies_hz / 1e6
        f_b = on_b.frequencies_hz / 1e6

        t = self._theme
        self.plot.add("ON — сессия A", f_a, on_a.amplitudes_db, t["curve_on_a"],   width=1, theme_key="curve_on_a")
        self.plot.add("ON — сессия B", f_b, on_b.amplitudes_db, t["curve_on_b"],   width=1, theme_key="curve_on_b")
        self.plot.add("Δ — сессия A",  f_a, diff_a,             t["curve_diff_a"], width=2, theme_key="curve_diff_a")
        self.plot.add("Δ — сессия B",  f_b, diff_b,             t["curve_diff_b"], width=2, theme_key="curve_diff_b")

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

        # Текст инструкции зависит от режима управления
        mode = self._control_mode
        settle = self._spin_settle.value()
        if mode == "semi_auto" and self._should_auto_control_test():
            if "ФОН ИЗМЕРЕН" in title:
                instruction = (
                    "Нажмите кнопку — тест включится автоматически.<br>"
                    f"<span style='color:#90CAF9'>Буфер стабилизации: {settle} мс.</span>"
                )
            elif "ВЕРИФИКАЦИЯ 1 ЗАВЕРШЕНА" in title:
                instruction = (
                    "Нажмите кнопку — тест выключится автоматически.<br>"
                    f"<span style='color:#90CAF9'>Буфер стабилизации: {settle} мс.</span>"
                )
        elif mode == "auto" and self._should_auto_control_test():
            # В автоматическом режиме эти диалоги не должны появляться
            # (workflow auto-advances), но на случай промежуточных пауз
            instruction = (
                "<span style='color:#aaa'>Автоматический режим — "
                "продолжение без участия оператора.</span>"
            )

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
            if self.wf.signals:
                self.plot.plot_signals(self.wf.signals)

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

        self._toggle_graph_fullscreen(False)
        self._stop_panorama_preview()   # также отключает хендлеры настроек
        self._bookmark_freqs_hz.clear()
        self.plot.clear()
        self.plot.clear_panorama_marks()
        self.plot.btn_mark_mode.setVisible(True)
        self.plot.btn_clear_marks.setVisible(True)
        self.table.setRowCount(0)
        self._reset_progress()
        self._stop_zero_span()
        self.live_widget.clear()
        self.live_widget.highlight_mark(None)
        self._spectrum_stack.setCurrentIndex(0)
        self.expert_panel.clear_signal()
        self.expert_panel.set_zero_span_active(False)
        self.expert_panel.enable_remeasure(False)

        self.lbl_instruction.setText("Подключите SDR для начала работы.")
        t = self._theme
        self.lbl_instruction.setStyleSheet(
            f"color: {t['text']}; font-size: 13px; padding: 10px;"
            f" background-color: {t['bg_instruction']}; border: 1px solid {t['border']};"
            f" border-radius: 4px;"
        )
        self._set_scan_mode(self.scan_mode)   # восстанавливает текст кнопки
        self.btn_action.setStyleSheet(
            f"QPushButton {{ background-color: #2196F3; color: white; font-weight: bold;"
            f" padding: 12px; border-radius: 4px; font-size: 14px; border: none; }}"
            f" QPushButton:hover {{ background-color: #1976D2; }}"
            f" QPushButton:disabled {{ background-color: {t['btn_bg']};"
            f" color: {t['text_off']}; }}"
        )
        self.btn_action.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.act_save.setEnabled(False)
        self.act_export_spectrum.setEnabled(False)
        self._last_on = None
        self._last_off = None
        self._last_diff = None
        self._set_settings_enabled(True)

    # ------------------------------------------------------------------
    # Метки из live-режима и панорамы
    # ------------------------------------------------------------------

    def _on_live_freq_marked(self, freq_mhz: float) -> None:
        freq_hz = freq_mhz * 1e6
        if not any(abs(f - freq_hz) < 100e3 for f in self._bookmark_freqs_hz):
            self._bookmark_freqs_hz.append(freq_hz)
        self._refresh_bookmark_table()

    def _on_live_marks_cleared(self) -> None:
        """Кнопка '✕ Метки' на live_widget — очищаем и список и таблицу."""
        self._bookmark_freqs_hz.clear()
        self.plot.clear_panorama_marks()
        self._refresh_bookmark_table()

    def _on_panorama_freq_marked(self, freq_mhz: float) -> None:
        """Пользователь поставил метку на панораме — сохраняем как закладку."""
        freq_hz = freq_mhz * 1e6
        if not any(abs(f - freq_hz) < 100e3 for f in self._bookmark_freqs_hz):
            self._bookmark_freqs_hz.append(freq_hz)
            if self.wf is not None and hasattr(self.wf, "update_bookmark_candidates"):
                self.wf.update_bookmark_candidates(self._bookmark_freqs_hz)
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

    def _set_progress(self, value: int) -> None:
        """Плавно анимирует прогрессбар к целевому значению."""
        self._prog_anim.stop()
        self._prog_anim.setStartValue(self.prog.value())
        self._prog_anim.setEndValue(value)
        self._prog_anim.start()

    def _reset_progress(self) -> None:
        """Мгновенно сбрасывает прогрессбар в 0, останавливая текущую анимацию."""
        self._prog_anim.stop()
        self.prog.setValue(0)

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
        self.expert_panel.enable_remeasure(True)
        # Сбрасываем прогрессбар — готово к новому поиску
        self._reset_progress()

    # ------------------------------------------------------------------
    # Удалённое управление тестовым клиентом
    # ------------------------------------------------------------------

    @property
    def _control_mode(self) -> str:
        """Текущий режим: 'manual' | 'semi_auto' | 'auto'."""
        return self._combo_mode.currentData()

    def _on_mode_changed(self, _: int) -> None:
        mode = self._control_mode
        # Буфер актуален только в полу- и автоматическом режимах
        enabled = (mode != "manual")
        self._spin_settle.setEnabled(enabled)
        self._lbl_settle.setEnabled(enabled)

    def _on_remote_client_count(self, count: int) -> None:
        # Вызывается из фонового потока — emit через signal безопасен
        self._remote_count_signal.emit(count)

    def _update_remote_status(self, count: int) -> None:
        self._lbl_remote_addr.setText(self._remote_server.local_address)
        if count == 0:
            self._lbl_remote_clients.setText("● Нет подключений")
            self._lbl_remote_clients.setStyleSheet(
                f"color: {self._theme['clients_off']};"
            )
        else:
            noun = "клиент" if count == 1 else ("клиента" if count < 5 else "клиентов")
            self._lbl_remote_clients.setText(f"● {count} {noun}")
            self._lbl_remote_clients.setStyleSheet("color:#66BB6A;")

    def _on_test_activate(self, active: bool) -> None:
        """Активирует/деактивирует тест: DemoSimulator + remote clients."""
        if isinstance(self.ctrl, DemoSimulator):
            self.ctrl.test_active = active
        if active:
            self._remote_server.send_test_start()
        else:
            self._remote_server.send_test_stop()

    def closeEvent(self, event) -> None:
        self._remote_server.stop()
        super().closeEvent(event)

    def _plot_data(self, on, off, diff):
        self._last_on = on
        self._last_off = off
        self._last_diff = diff
        f_mhz = on.frequencies_hz / 1e6
        x_min, x_max = float(f_mhz.min()), float(f_mhz.max())

        self.plot.clear()
        # Скрываем кнопки меток — метки уже переданы в workflow, дальше они не нужны
        self.plot.btn_mark_mode.setVisible(False)
        self.plot.btn_clear_marks.setVisible(False)
        self.plot.set_freq_range(x_min, x_max)
        self.plot.add("ON (Test)",   f_mhz, on.amplitudes_db,  self._theme["curve_on"],   width=0.8, theme_key="curve_on")
        self.plot.add("OFF (Noise)", f_mhz, off.amplitudes_db, self._theme["curve_off"],  width=0.8, theme_key="curve_off")
        self.plot.add("Difference",  f_mhz, diff,              self._theme["curve_diff"], width=0.8, theme_key="curve_diff")
        self.plot.set_threshold(self.cfg.threshold_db, [x_min, x_max])

        if self.wf and hasattr(self.wf, "signals"):
            self._update_table_from_signals(self.wf.signals)
            self.plot.plot_signals(self.wf.signals)

        self.plot.reset_zoom()

    def _update_table_only(self):
        if self.wf and hasattr(self.wf, "signals"):
            if self.wf.signals:
                self._update_table_from_signals(self.wf.signals)
            else:
                # Сигналов ещё нет — показываем метки пока идёт фаза 1
                self._refresh_bookmark_table()

    # ------------------------------------------------------------------
    # Таблица результатов
    # ------------------------------------------------------------------

    def _update_table_from_signals(self, signals):
        COLOR_WAIT    = "#9E9E9E"
        COLOR_SUCCESS = "#66BB6A"
        COLOR_FAIL_V1 = "#EF5350"
        COLOR_EXTERNAL = "#42A5F5"
        COLOR_WARN    = "#FFCA28"

        item_flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                      | Qt.ItemFlag.ItemIsEditable)

        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)

        count = len(signals)
        self.table.setRowCount(count)

        if count == 0:
            self.table.blockSignals(False)
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
                for col, item in enumerate([item_freq, item_diff, item_on,
                                            item_off, item_harm, item_status]):
                    item.setFlags(item_flags)
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

            for col, item in enumerate([item_freq, item_diff, item_on,
                                        item_off, item_harm, item_status]):
                item.setFlags(item_flags)
            self.table.setItem(i, 0, item_freq)
            self.table.setItem(i, 1, item_diff)
            self.table.setItem(i, 2, item_on)
            self.table.setItem(i, 3, item_off)
            self.table.setItem(i, 4, item_harm)
            self.table.setItem(i, 5, item_status)

        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self.table.setSortingEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
