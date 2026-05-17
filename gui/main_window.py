import sys
import os
import csv
import types
import numpy as np
import pyqtgraph as pg
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QTableWidget, QTableWidgetItem, QLabel,
                             QProgressBar, QMessageBox, QGroupBox, QHeaderView,
                             QApplication, QFileDialog, QDoubleSpinBox, QSpinBox,
                             QCheckBox, QStackedWidget, QComboBox, QTabWidget,
                             QStyledItemDelegate, QAbstractItemDelegate, QFrame, QMenu,
                             QSizePolicy)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtGui import QColor, QAction, QActionGroup, QIcon
from core.config import PanoramaConfig
from core.backends import BaseInstrument, RtlSdrBackend, DemoSimulator, HackRfBackend
from core.models import Spectrum, PEMINSignal
from core.methods import PanoramaDiffWorkflow, HarmonicSearchWorkflow
from core.audio_monitor import AudioMonitor
from core.zero_span import ZeroSpanWorker
from core.remote_control_server import RemoteControlServer
from gui.spectrum_widget import SpectrumPlotWidget, _marker_color
from gui.expert_panel import ExpertPanel
from gui.zero_span_widget import ZeroSpanWidget
from gui.live_widget import LiveWidget
from gui.theme import DARK, LIGHT, btn_primary, btn_danger
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

    # (label, tbl_status_key, semantic_key)
    _OPTIONS = [
        ("ПЭМИН",           "ok",   "green"),
        ("Брак (В1)",        "fail", "red"),
        ("Внешний (В2)",     "ext",  "blue"),
        ("Двойной брак",     "ext",  "blue"),
        ("В1 OK",            "warn", "yellow"),
        ("Ожидание",         "wait", "yellow"),
        ("Потенциальный",    "warn", "yellow"),
        ("Гармоник нет",     "fail", "red"),
    ]

    # Обновляются через set_theme()
    _bg       = "#2b2b2b"
    _fg       = "#e0e0e0"
    _border   = "#555555"
    _sel_bg   = "#1565C0"
    _sel_fg   = "#ffffff"
    _theme_dict: dict = DARK

    def set_theme(self, t: dict) -> None:
        self._theme_dict = t
        self._bg     = t["bg_widget"]
        self._fg     = t["text"]
        self._border = t["border_input"]
        if t["name"] == "dark":
            self._sel_bg = "#1E88E5"
            self._sel_fg = "#ffffff"
        else:
            self._sel_bg = "#1565C0"
            self._sel_fg = "#ffffff"

    def color_for(self, text: str) -> str:
        for label, color_key, _ in self._OPTIONS:
            if label in text:
                return self._theme_dict.get(f"tbl_status_{color_key}",
                                            self._theme_dict["tbl_status_wait"])
        return self._theme_dict["tbl_status_wait"]

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
            f"QComboBox {{ background-color: {self._bg}; color: {self._fg};"
            f" border: 1px solid {self._border}; padding: 2px 6px; }}"
            f" QComboBox::drop-down {{ border: none; }}"
        )
        combo.view().setStyleSheet(
            f"QListView {{"
            f" background-color: {self._bg}; color: {self._fg}; }}"
            f" QListView::item {{"
            f" padding: 4px 8px; color: {self._fg};"
            f" background-color: {self._bg}; }}"
            f" QListView::item:hover, QListView::item:selected {{"
            f" background-color: {self._sel_bg}; color: {self._sel_fg}; }}"
        )

        combo.activated.connect(
            lambda _: (self.commitData.emit(combo),
                       self.closeEditor.emit(
                           combo, QAbstractItemDelegate.EndEditHint.NoHint))
        )
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
        self.setWindowTitle("ПЭМИН Детектор")
        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "image", "icon.png")
        self.setWindowIcon(QIcon(_icon_path))
        self.resize(1200, 800)

        self.setStyleSheet(
            "QMainWindow { background-color: #14171c; }"
        )

        self._theme = DARK
        self.cfg = PanoramaConfig()
        self._hw = "rtlsdr"
        self._live_bw_hz  = 2_000_000
        self._freq_min_hz = 24e6
        self._freq_max_hz = 1750e6
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
        self._zs_freq_hz: float | None = None
        self._panorama_preview_worker: LiveWorker | None = None
        self._bookmark_freqs_hz: list[float] = []   # частоты (Гц), отмеченные в live

        self.scan_mode = "full"   # "full"|"quick"|"harmonic"|"simulator"|"demo"

        self._remote_server = RemoteControlServer()
        self._remote_server.on_client_count_changed = self._on_remote_client_count
        self._remote_count_signal.connect(self._update_remote_status)
        self._remote_server.start()

        self._init_ui()
        self._setup_menus()
        self.menuBar().hide()
        self._update_remote_status(0)
        self.apply_theme(DARK)

    def _build_app_bar(self) -> QWidget:
        """Кастомная строка приложения: логотип, меню, статус-пилюли."""
        bar = QFrame()
        bar.setObjectName("AppBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(0)
        bar.setFixedHeight(44)

        # Логотип — иконка + имя
        _logo_icon = QWidget()
        _logo_icon.setObjectName("AppLogoIcon")
        _logo_icon.setFixedSize(22, 22)
        _lic = QHBoxLayout(_logo_icon)
        _lic.setContentsMargins(0, 0, 0, 0)
        _lic_lbl = QLabel("◉")
        _lic_lbl.setObjectName("AppLogoGlyph")
        _lic_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _lic.addWidget(_lic_lbl)
        lay.addWidget(_logo_icon)
        lay.addSpacing(8)

        _logo_name = QLabel("ПЭМИН Детектор")
        _logo_name.setObjectName("AppLogoName")
        lay.addWidget(_logo_name)
        lay.addSpacing(16)

        # Разделитель
        _sep = QWidget()
        _sep.setObjectName("AppBarSep")
        _sep.setFixedWidth(1)
        _sep.setFixedHeight(18)
        lay.addWidget(_sep)
        lay.addSpacing(4)

        # Меню-кнопки
        self._menu_btns: dict[str, QPushButton] = {}
        for name in ("Режим", "Действие", "Устройство", "Вид"):
            btn = QPushButton(name)
            btn.setObjectName("AppMenuBtn")
            btn.setFlat(True)
            self._menu_btns[name] = btn
            lay.addWidget(btn)
        # Меню будут привязаны в _setup_menus после создания

        # Spacer
        lay.addStretch(1)

        # Пилюля клиентов
        self._pill_clients = QLabel("● Нет клиентов")
        self._pill_clients.setObjectName("AppPill")
        lay.addWidget(self._pill_clients)
        lay.addSpacing(6)

        # Пилюля устройства
        self._pill_device = QLabel("RTL-SDR")
        self._pill_device.setObjectName("AppPill")
        lay.addWidget(self._pill_device)
        lay.addSpacing(6)

        # Пилюля режима
        self._pill_mode = QLabel("Метод разности")
        self._pill_mode.setObjectName("AppPill")
        lay.addWidget(self._pill_mode)
        lay.addSpacing(8)

        # Кнопка смены темы
        self._btn_theme_toggle = QPushButton("◑")
        self._btn_theme_toggle.setObjectName("AppIconBtn")
        self._btn_theme_toggle.setFixedSize(28, 28)
        self._btn_theme_toggle.setToolTip("Переключить тему")
        self._btn_theme_toggle.clicked.connect(self._toggle_theme)
        lay.addWidget(self._btn_theme_toggle)

        return bar

    def _setup_menus(self):
        mb = self.menuBar()

        # ── Режим ─────────────────────────────────────────────────────
        menu_mode = QMenu(self)
        self._menu_btns["Режим"].clicked.connect(
            lambda: menu_mode.exec(self._menu_btns["Режим"].mapToGlobal(
                self._menu_btns["Режим"].rect().bottomLeft()))
        )

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

        self.act_mode_harmonic = QAction("Метод поиска по гармоникам", self)
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

        menu_mode.addSeparator()
        # Не входит в эксклюзивную группу — работает совместно с любым методом
        self.act_expert_mode = QAction("Экспертный режим", self)
        self.act_expert_mode.setCheckable(True)
        self.act_expert_mode.setToolTip(
            "После завершения измерений открывает расширенный режим:\n"
            "редактирование таблицы, удаление и добавление сигналов,\n"
            "подсказки по классификации, экспорт CSV."
        )
        menu_mode.addAction(self.act_expert_mode)
        # expert_panel создан в _init_ui() (раньше _setup_menu_bar), подключаем здесь
        self.act_expert_mode.toggled.connect(self._on_expert_mode_toggled)

        # ── Действие ──────────────────────────────────────────────────
        menu_action = QMenu(self)
        self._menu_btns["Действие"].clicked.connect(
            lambda: menu_action.exec(self._menu_btns["Действие"].mapToGlobal(
                self._menu_btns["Действие"].rect().bottomLeft()))
        )

        self.act_load = QAction("Загрузить измерение", self)
        self.act_load.setShortcut("Ctrl+O")
        self.act_load.triggered.connect(self._load_measurement)
        menu_action.addAction(self.act_load)

        self.act_compare = QAction("Сравнить две сессии", self)
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

        # ── Устройство ────────────────────────────────────────────────
        menu_hw = QMenu(self)
        self._menu_btns["Устройство"].clicked.connect(
            lambda: menu_hw.exec(self._menu_btns["Устройство"].mapToGlobal(
                self._menu_btns["Устройство"].rect().bottomLeft()))
        )
        hw_group = QActionGroup(self)
        hw_group.setExclusive(True)

        self.act_hw_rtlsdr = QAction("RTL-SDR", self)
        self.act_hw_rtlsdr.setCheckable(True)
        self.act_hw_rtlsdr.setChecked(True)
        self.act_hw_rtlsdr.triggered.connect(lambda: self._set_hw("rtlsdr"))
        hw_group.addAction(self.act_hw_rtlsdr)
        menu_hw.addAction(self.act_hw_rtlsdr)

        self.act_hw_hackrf = QAction("HackRF One", self)
        self.act_hw_hackrf.setCheckable(True)
        self.act_hw_hackrf.triggered.connect(lambda: self._set_hw("hackrf"))
        hw_group.addAction(self.act_hw_hackrf)
        menu_hw.addAction(self.act_hw_hackrf)

        # ── Вид ───────────────────────────────────────────────────────
        menu_view = QMenu(self)
        self._menu_btns["Вид"].clicked.connect(
            lambda: menu_view.exec(self._menu_btns["Вид"].mapToGlobal(
                self._menu_btns["Вид"].rect().bottomLeft()))
        )
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
        # Сохранить ссылки на меню для apply_theme
        self._menu_mode = menu_mode
        self._menu_action_menu = menu_action
        self._menu_hw = menu_hw
        self._menu_view = menu_view

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
        _mode_pill_labels = {
            "full":       "Метод разности",
            "quick":      "Быстрое обнаруж.",
            "harmonic":   "Поиск гармоник",
            "simulator":  "Симулятор",
            "demo":       "Демо-режим",
        }
        self._pill_mode.setText(_mode_pill_labels.get(mode, mode))
        # Колонка «Гармоники» — только для harmonic-режима
        self.table.setColumnHidden(4, mode != "harmonic")

    # ------------------------------------------------------------------
    # Выбор устройства
    # ------------------------------------------------------------------

    def _set_hw(self, hw: str) -> None:
        if hw == self._hw:
            return
        if self.current_step != "idle":
            self._hw = hw
            self._reset_to_start()
            return
        self._hw = hw
        self._update_hw_limits()
        _hw_labels = {"rtlsdr": "RTL-SDR", "hackrf": "HackRF One"}
        self._pill_device.setText(_hw_labels.get(hw, hw))

    def _toggle_theme(self) -> None:
        from gui.theme import DARK, LIGHT
        if self._theme is DARK:
            self.apply_theme(LIGHT)
            self.act_theme_light.setChecked(True)
        else:
            self.apply_theme(DARK)
            self.act_theme_dark.setChecked(True)

    # Дефолты по устройствам: (start_mhz, stop_mhz, avg_count)
    _HW_DEFAULTS = {
        "hackrf":  (100.0, 110.0, 50),
        "rtlsdr":  (102.0, 104.0, 50),
        "demo":    (102.0, 104.0, 50),
    }

    def _update_hw_limits(self) -> None:
        """Обновляет лимиты частот, live BW и дефолтные параметры под текущий бэкенд."""
        if self._hw == "hackrf":
            self._live_bw_hz  = 10_000_000
            self._freq_min_hz = 1e6
            self._freq_max_hz = 6000e6
            self.spin_start_freq.setRange(1, 6000)
            self.spin_stop_freq.setRange(2, 6000)
            self.spin_gain.setRange(0, 62)
            self.setWindowTitle("ПЭМИН Детектор")
        else:
            self._live_bw_hz  = 2_000_000
            self._freq_min_hz = 24e6
            self._freq_max_hz = 1750e6
            self.spin_start_freq.setRange(24, 1750)
            self.spin_stop_freq.setRange(25, 1750)
            self.spin_gain.setRange(0, 50)
            self.setWindowTitle("ПЭМИН Детектор")

        start_mhz, stop_mhz, avg = self._HW_DEFAULTS.get(self._hw, (102.0, 104.0, 50))
        self.spin_start_freq.blockSignals(True)
        self.spin_stop_freq.blockSignals(True)
        self.spin_start_freq.setValue(start_mhz)
        self.spin_stop_freq.setValue(stop_mhz)
        self.spin_start_freq.blockSignals(False)
        self.spin_stop_freq.blockSignals(False)
        self.spin_avg.setValue(avg)

    def _make_backend(self) -> BaseInstrument:
        """Создать экземпляр бэкенда под текущий self._hw."""
        if self._hw == "hackrf":
            if HackRfBackend is None:
                raise RuntimeError(
                    "Библиотека hackrf не установлена.\n"
                    "Установите: conda install -c conda-forge hackrf\n"
                    "или: pip install hackrf"
                )
            return HackRfBackend()
        if RtlSdrBackend is None:
            raise RuntimeError(
                "Библиотека pyrtlsdr не установлена.\n"
                "Установите: conda install -c conda-forge pyrtlsdr"
            )
        return RtlSdrBackend()

    # ------------------------------------------------------------------
    # Тема оформления
    # ------------------------------------------------------------------

    def apply_theme(self, t: dict) -> None:
        self._theme = t
        self._status_delegate.set_theme(t)

        # Главное окно + все objectName-стили (§15.12)
        self.setStyleSheet(
            f"QMainWindow {{ background-color: {t['bg_window']}; }}"
            f" QGroupBox {{ font-weight: bold; border: 1px solid {t['border']};"
            f" border-radius: 5px; margin-top: 10px; padding-top: 10px; color: {t['text']}; }}"
            f" QGroupBox::title {{ subcontrol-origin: margin; left: 10px;"
            f" padding: 0 5px 0 5px; }}"
            # Action bar
            f" #ActionBar {{ background: {t['bg_widget']};"
            f" border-bottom: 1px solid {t['border']}; }}"
            f" #StatusIcon {{ background: {t['bg_input']}; border-radius: 8px;"
            f" color: {t['btn_active']}; font-size: 16px; }}"
            f" #StatusTitle {{ color: {t['text_muted']}; font-size: 10px;"
            f" letter-spacing: 0.08em; }}"
            f" #Instruction {{ color: {t['text']}; font-size: 13px; }}"
            # Settings bar — поля с bg_widget фоном на тёмном bg_window
            f" #SettingsField {{ background: {t['bg_widget']}; border-radius: 4px;"
            f" border: 1px solid {t['border']}; }}"
            f" #FieldLabel {{ color: {t['text_dim']}; font-size: 11px;"
            f" letter-spacing: 0.04em; }}"
            # Checkboxes
            f" QCheckBox {{ color: {t['text_dim']}; font-size: 12px; }}"
            f" QCheckBox::indicator {{ width: 14px; height: 14px;"
            f" border: 1px solid {t['border_input']}; border-radius: 3px;"
            f" background: {t['bg_input']}; }}"
            f" QCheckBox::indicator:checked {{ background: {t['btn_primary_bg']};"
            f" border-color: {t['btn_primary_bg']}; }}"
            # Sidebar section headers / mono values
            f" #SidebarSection {{ color: {t['text_muted']}; font-size: 10px;"
            f" letter-spacing: 0.08em; padding-bottom: 4px; }}"
            f" #MonoValue {{ font-family: monospace; color: {t['text']}; }}"
            # Tools chip (над графиком)
            f" #ToolsChip {{ background: {t['bg_widget']}; border: 1px solid {t['border']};"
            f" border-radius: 8px; }}"
            # Обёртка спектра
            f" #SpectrumFrame {{ background: {t['bg_widget']}; }}"
        )

        # Кастомный app bar
        self._app_bar.setStyleSheet(
            f"QFrame#AppBar {{ background: {t['bg_widget']};"
            f" border-bottom: 1px solid {t['border']}; }}"
            f" QWidget#AppLogoIcon {{ background: {t['btn_active']}; border-radius: 5px; }}"
            f" QLabel#AppLogoGlyph {{ color: white; font-size: 13px; }}"
            f" QLabel#AppLogoName {{ color: {t['text']}; font-size: 13px; font-weight: 700;"
            f" letter-spacing: -0.01em; }}"
            f" QWidget#AppBarSep {{ background: {t['border_input']}; }}"
            f" QPushButton#AppMenuBtn {{ background: transparent; color: {t['text_dim']};"
            f" font-size: 12px; padding: 4px 10px; border: none; border-radius: 6px; }}"
            f" QPushButton#AppMenuBtn:hover {{ background: {t['bg_input']}; color: {t['text']};"
            f" border: 1px solid {t['border']}; }}"
            f" QPushButton#AppMenuBtn:pressed {{ background: {t['border']}; }}"
            f" QLabel#AppPill {{ color: {t['text_dim']}; font-size: 12px;"
            f" padding: 4px 12px; border-radius: 999px;"
            f" background: {t['bg_input']}; border: 1px solid {t['border']}; }}"
            f" QPushButton#AppIconBtn {{ background: transparent; color: {t['text_dim']};"
            f" font-size: 16px; border: none; border-radius: 6px; }}"
            f" QPushButton#AppIconBtn:hover {{ background: {t['bg_input']}; color: {t['text']}; }}"
        )
        # Сбросить инлайн-стили пилюль — иначе они не обновятся при смене темы
        self._pill_clients.setStyleSheet("")
        self._pill_device.setStyleSheet("")
        self._pill_mode.setStyleSheet("")
        # Стиль для всплывающих меню (QMenu не наследует из app_bar)
        _menu_qss = (
            f"QMenu {{ background-color: {t['menu_bg']}; color: {t['mb_fg']};"
            f" border: 1px solid {t['menu_bdr']}; border-radius: 6px; padding: 4px; }}"
            f" QMenu::item {{ padding: 5px 16px 5px 12px; border-radius: 4px; }}"
            f" QMenu::item:selected {{ background-color: {t['menu_sel']}; color: {t['text']}; }}"
            f" QMenu::separator {{ height: 1px; background: {t['menu_bdr']}; margin: 4px 0; }}"
        )
        for menu in (self._menu_mode, self._menu_action_menu, self._menu_hw, self._menu_view):
            menu.setStyleSheet(_menu_qss)

        # Прогресс-бар — прозрачный фон, видна только заливка chunk
        self.prog.setStyleSheet(
            f"QProgressBar {{ border: none; border-radius: 0px;"
            f" background-color: transparent; }}"
            f" QProgressBar::chunk {{ background-color: {t['progress_chunk']}; }}"
        )

        # Кнопка СБРОС — через единый helper
        self.btn_stop.setStyleSheet(btn_danger(t, large=True))

        # Таблица результатов
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {t['bg_table']};"
            f" alternate-background-color: {t['bg_table_alt']};"
            f" color: {t['text']}; gridline-color: {t['border']};"
            f" border: 1px solid {t['border']}; }}"
            f" QHeaderView::section {{ background-color: {t['bg_header']}; color: {t['text']};"
            f" padding: 5px 4px; border: 1px solid {t['border']}; font-weight: bold; }}"
            f" QTableWidget::item {{ padding: 4px 14px; }}"
            f" QTableWidget::item:selected {{ background-color: {t['btn_active']}; color: white; }}"
        )
        self.table.verticalHeader().setDefaultSectionSize(32)

        # Action bar: иконка + статус (стили задаются через глобальный QSS #objectName)
        self._lbl_status_icon.setStyleSheet("")
        self._lbl_status_title.setStyleSheet("")
        self.lbl_instruction.setStyleSheet("")

        # Панель удалённого управления
        self._remote_box.setStyleSheet(
            f"QLabel {{ color: {t['text_dim']}; font-size: 12px; }}"
            f" QSpinBox, QComboBox {{ background: {t['bg_input']}; color: {t['text']};"
            f" border: 1px solid {t['border_input']}; border-radius: 4px; padding: 2px 4px; }}"
            f" QComboBox::drop-down {{ border: none; }}"
            f" QComboBox QAbstractItemView {{ background: {t['bg_widget']}; color: {t['text']};"
            f" selection-background-color: {t['mb_sel']}; }}"
        )
        self._lbl_remote_addr.setStyleSheet(
            f"color: {t['remote_addr']}; font-family: monospace;"
        )

        # Панель параметров — локальный stylesheet (блокирует глобальный для детей)
        self._settings_panel.setStyleSheet(
            # Фон самой панели
            f"QWidget#SettingsPanel {{ background-color: {t['bg_window']};"
            f" border-bottom: 1px solid {t['border']}; }}"
            # Поля — светлее панели
            f" QFrame#SettingsField {{ background: {t['bg_widget']}; border-radius: 4px;"
            f" border: 1px solid {t['border_input']}; }}"
            # Метки полей — полная яркость, жирный
            f" QLabel#FieldLabel {{ color: {t['text']}; font-size: 11px;"
            f" font-weight: 600; letter-spacing: 0.04em;"
            f" background: transparent; }}"
            # Стрелка между частотами
            f" QLabel#SettingsArrow {{ color: {t['text_dim']}; font-size: 12px;"
            f" background: transparent; }}"
            # Спинбоксы
            f" QDoubleSpinBox, QSpinBox {{ background-color: {t['bg_input']}; color: {t['text']};"
            f" border: 1px solid {t['border_input']}; border-radius: 4px;"
            f" font-family: monospace; font-size: 13px; font-weight: 500;"
            f" padding: 5px 10px; min-width: 64px; min-height: 28px; }}"
            # Чекбоксы
            f" QCheckBox {{ color: {t['text']}; font-size: 12px;"
            f" background: transparent; }}"
            f" QCheckBox::indicator {{ width: 14px; height: 14px;"
            f" border: 1px solid {t['border_input']}; border-radius: 3px;"
            f" background: {t['bg_input']}; }}"
            f" QCheckBox::indicator:checked {{ background: {t['btn_primary_bg']};"
            f" border-color: {t['btn_primary_bg']}; }}"
        )

        # Кнопка действия
        # Кнопка действия — через единый helper
        self.btn_action.setStyleSheet(btn_primary(t, large=True))

        # Панель действия — стиль задан через #ActionBar в глобальном QSS
        self._action_bar.setStyleSheet("")

        # Боковая панель (вкладки)
        self._sidebar.setStyleSheet(
            f"QTabWidget::pane {{ border-left: 1px solid {t['border']};"
            f" border-top: none; background: {t['bg_widget']}; }}"
            f" QTabBar::tab {{ background: {t['bg_window']}; color: {t['text_muted']};"
            f" padding: 10px 8px; margin: 4px 2px 0 2px;"
            f" border: 1px solid {t['border']}; border-bottom: none;"
            f" border-radius: 6px 6px 0 0;"
            f" font-size: 12px; text-align: center; }}"
            f" QTabBar::tab:selected {{ background: {t['bg_widget']}; color: {t['text']};"
            f" border-color: {t['border_input']};"
            f" border-bottom: 2px solid {t['btn_active']}; }}"
            f" QTabBar::tab:hover {{ background: {t['bg_input']}; color: {t['text']}; }}"
        )

        # Фон обёртки сайдбара
        self._sidebar_frame.setStyleSheet(
            f"QFrame#SidebarFrame {{ background-color: {t['bg_widget']}; }}"
        )

        # Дочерние виджеты с pyqtgraph
        self.plot.apply_theme(t)
        self.live_widget.apply_theme(t)
        self.zero_span_widget.apply_theme(t)
        self.expert_panel.apply_theme(t)

        # Перекрасить статусы в таблице и маркеры ПЭМИН на графике
        self._refresh_table_colors()
        if self.wf and hasattr(self.wf, "signals") and self.wf.signals:
            self.plot.plot_signals(self.wf.signals)

    def _init_ui(self):
        w = QWidget()
        self.setCentralWidget(w)
        main_layout = QVBoxLayout(w)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # ── Кастомный app bar (логотип + меню + пилюли) ───────────────
        self._app_bar = self._build_app_bar()
        main_layout.addWidget(self._app_bar)

        # ── Панель действия (инструкция + кнопки + прогресс) ──────────
        self._action_bar = QWidget()
        self._action_bar.setObjectName("ActionBar")
        action_bar_layout = QVBoxLayout(self._action_bar)
        action_bar_layout.setContentsMargins(0, 0, 0, 0)
        action_bar_layout.setSpacing(0)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(14, 8, 14, 24)
        action_row.setSpacing(12)

        # Иконка состояния — 32×32 px, фон bg_input через #StatusIcon QSS
        self._lbl_status_icon = QLabel("◎")
        self._lbl_status_icon.setObjectName("StatusIcon")
        self._lbl_status_icon.setFixedSize(32, 32)
        self._lbl_status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_row.addWidget(self._lbl_status_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        # Двухстрочный статус: заголовок фазы + описание
        status_block = QVBoxLayout()
        status_block.setSpacing(1)
        status_block.setContentsMargins(0, 0, 0, 0)

        self._lbl_status_title = QLabel("ГОТОВ")
        self._lbl_status_title.setObjectName("StatusTitle")

        self.lbl_instruction = QLabel("Подключите SDR для начала работы.")
        self.lbl_instruction.setWordWrap(True)
        self.lbl_instruction.setObjectName("Instruction")
        self.lbl_instruction.setMinimumHeight(18)
        self.lbl_instruction.setMaximumHeight(60)
        self.lbl_instruction.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        status_block.addWidget(self._lbl_status_title)
        status_block.addWidget(self.lbl_instruction)
        action_row.addLayout(status_block, 1)

        self.btn_stop = QPushButton("Сброс")
        self.btn_stop.setFixedHeight(34)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._reset_to_start)
        action_row.addWidget(self.btn_stop)

        self.btn_action = QPushButton("Подключить и начать")
        self.btn_action.setFixedHeight(34)
        self.btn_action.clicked.connect(self._on_control_button_clicked)
        action_row.addWidget(self.btn_action)

        action_bar_layout.addLayout(action_row)

        self.prog = QProgressBar()
        self.prog.setTextVisible(False)
        self.prog.setFixedHeight(2)
        self.prog.setVisible(False)
        action_bar_layout.addWidget(self.prog)

        main_layout.addWidget(self._action_bar)

        # Плавная анимация прогрессбара
        self._prog_anim = QPropertyAnimation(self.prog, b"value")
        self._prog_anim.setDuration(450)
        self._prog_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Таймер буферизации для полуавтоматического режима
        self._settle_timer = QTimer()
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._finish_semi_auto_resume)

        # ── Панель параметров измерения ────────────────────────────────
        self._settings_panel = self._create_settings_panel()
        main_layout.addWidget(self._settings_panel)

        # ── Основная область: спектр + боковая панель ─────────────────
        self._main_area = QWidget()
        self._main_area.setSizePolicy(
            self._main_area.sizePolicy().horizontalPolicy(),
            self._main_area.sizePolicy().verticalPolicy()
        )
        main_area_layout = QHBoxLayout(self._main_area)
        main_area_layout.setSpacing(0)
        main_area_layout.setContentsMargins(0, 0, 0, 0)

        # График спектра / Zero Span / Live (QStackedWidget)
        self.plot = SpectrumPlotWidget()
        self.plot.freq_clicked.connect(self._on_graph_click)
        self.plot.freq_mark_added.connect(self._on_panorama_freq_marked)
        self.zero_span_widget = ZeroSpanWidget()
        self.zero_span_widget.audio_toggled.connect(self._on_zs_audio_toggle)
        self.zero_span_widget.pause_requested.connect(self._on_zs_pause)
        self.zero_span_widget.resume_requested.connect(self._on_zs_resume)
        self.zero_span_widget.fullscreen_toggled.connect(self._toggle_graph_fullscreen)
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
        self._spectrum_stack.addWidget(self.plot)              # index 0 — спектр
        self._spectrum_stack.addWidget(self.zero_span_widget)  # index 1 — нулевой обзор
        self._spectrum_stack.addWidget(self.live_widget)       # index 2 — прямой эфир

        # Обёртка для визуального отделения графика от настроек и сайдбара
        self._spectrum_frame = QFrame()
        self._spectrum_frame.setObjectName("SpectrumFrame")
        _sf_layout = QVBoxLayout(self._spectrum_frame)
        _sf_layout.setContentsMargins(14, 14, 14, 14)
        _sf_layout.setSpacing(0)
        _sf_layout.addWidget(self._spectrum_stack)
        main_area_layout.addWidget(self._spectrum_frame, 1)

        # ── Боковая панель (вкладки) ───────────────────────────────────
        self._sidebar = QTabWidget()
        self._sidebar.setMinimumWidth(500)
        self._sidebar.setMaximumWidth(640)
        self._sidebar.setDocumentMode(True)
        self._sidebar.tabBar().setExpanding(True)
        self._sidebar.tabBar().setDrawBase(False)

        # Вкладка 0: Результаты
        results_tab = QWidget()
        results_layout = QVBoxLayout(results_tab)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(0)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Частота, МГц", "Δ, дБ", "Сигнал, дБ", "Шум, дБ", "Гармоники", "Статус"]
        )
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        # Пропорциональные ширины через ResizeMode.Fixed + растяжение вручную
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)   # Частота
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)     # Δ дБ
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # Сигнал
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)   # Шум
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)   # Гармоники
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)   # Статус
        self.table.setColumnWidth(1, 58)   # Δ дБ — фиксированная узкая
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Переставить Δ, дБ (лог. колонка 1) на предпоследнюю позицию визуально
        header.moveSection(1, 4)
        self.table.setColumnHidden(4, True)   # «Гармоники» — скрыта до активации метода
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self._status_delegate = _StatusDelegate(self.table)
        self.table.setItemDelegateForColumn(5, self._status_delegate)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        results_layout.addWidget(self.table)
        self._sidebar.addTab(results_tab, "Результаты")

        # Вкладка 1: Удалённое управление
        remote_tab = self._create_remote_panel()
        self._sidebar.addTab(remote_tab, "Удалённое\nуправление")

        # Вкладка 2: Эксперт
        expert_tab = QWidget()
        expert_tab_layout = QVBoxLayout(expert_tab)
        expert_tab_layout.setContentsMargins(0, 0, 0, 0)
        expert_tab_layout.setSpacing(0)

        self.expert_panel = ExpertPanel()
        self.expert_panel.signal_modified.connect(self._on_expert_signal_modified)
        self.expert_panel.zero_span_started.connect(self._on_zero_span_start)
        self.expert_panel.zero_span_stopped.connect(self._on_zero_span_stop)
        self.expert_panel.delete_requested.connect(self._on_expert_delete_requested)
        expert_tab_layout.addWidget(self.expert_panel)
        expert_tab_layout.addStretch(1)
        self._sidebar.addTab(expert_tab, "Экспертный\nанализ")
        self._sidebar.tabBar().setTabVisible(2, False)  # скрыта до включения режима

        # Подписываемся на сигналы модели таблицы для автообновления
        # счётчика вкладки «Результаты» без явных вызовов в каждом методе.
        self.table.model().rowsInserted.connect(self._refresh_sidebar_tab_titles)
        self.table.model().rowsRemoved.connect(self._refresh_sidebar_tab_titles)
        self.table.model().modelReset.connect(self._refresh_sidebar_tab_titles)

        # Двойной клик → переход на вкладку «Эксперт»
        self.table.itemDoubleClicked.connect(self._on_table_double_clicked)

        self._sidebar_frame = QFrame()
        self._sidebar_frame.setObjectName("SidebarFrame")
        _sfl = QVBoxLayout(self._sidebar_frame)
        _sfl.setContentsMargins(0, 14, 14, 14)
        _sfl.setSpacing(0)
        _sfl.addWidget(self._sidebar)
        main_area_layout.addWidget(self._sidebar_frame)
        main_layout.addWidget(self._main_area, 1)

    # ------------------------------------------------------------------
    # Заголовки вкладок сайдбара (с бейджами/счётчиками)
    # ------------------------------------------------------------------

    def _refresh_sidebar_tab_titles(self) -> None:
        """Обновляет тексты вкладок:
        — «Результаты (N)» если есть обнаружения
        — «Эксперт · 103.8» если выбран сигнал
        """
        from PyQt6.QtGui import QColor

        # Таб 0: Результаты + счётчик
        n = self.table.rowCount()
        self._sidebar.setTabText(0, f"Результаты ({n})" if n > 0 else "Результаты")

        # Таб 2: Эксперт + бейдж с частотой
        sig = getattr(self.expert_panel, "_signal", None)
        if sig is not None:
            mhz = sig.frequency_hz / 1e6
            badge = f"{mhz/1000:.2f} ГГц" if mhz >= 1000 else f"{mhz:.1f}"
            self._sidebar.setTabText(2, f"Экспертный\nанализ · {badge}")
            # Подсвечиваем вкладку акцентным цветом для визуального бейджа
            self._sidebar.tabBar().setTabTextColor(
                2, QColor(self._theme["btn_active"])
            )
        else:
            self._sidebar.setTabText(2, "Экспертный\nанализ")
            # Сброс к стандартному цвету текста
            self._sidebar.tabBar().setTabTextColor(2, QColor())

    # ------------------------------------------------------------------
    # Хелпер обновления статуса в action bar
    # ------------------------------------------------------------------

    def _set_status(self, title: str, text: str, icon: str = "◎") -> None:
        """Устанавливает иконку, заголовок фазы и текст описания в action bar."""
        self._lbl_status_icon.setText(icon)
        self._lbl_status_title.setText(title.upper() if title else "")
        self.lbl_instruction.setText(text)

    # ------------------------------------------------------------------
    # Панель параметров
    # ------------------------------------------------------------------

    def _create_settings_panel(self) -> QWidget:
        box = QWidget()
        box.setObjectName("SettingsPanel")
        box.setFixedHeight(90)
        sp = QHBoxLayout(box)
        sp.setContentsMargins(12, 8, 12, 8)
        sp.setSpacing(4)

        def spin_d(min_v, max_v, val, step=1.0, decimals=1):
            s = QDoubleSpinBox()
            s.setRange(min_v, max_v)
            s.setValue(val)
            s.setSingleStep(step)
            s.setDecimals(decimals)
            return s

        def make_field(label_text: str, min_width: int = 110):
            f = QFrame()
            f.setObjectName("SettingsField")
            f.setMinimumWidth(min_width)
            f.setFixedHeight(70)
            v = QVBoxLayout(f)
            v.setContentsMargins(10, 6, 10, 14)
            v.setSpacing(3)
            lbl = QLabel(label_text)
            lbl.setObjectName("FieldLabel")
            v.addWidget(lbl)
            return f, v

        # ── ДИАПАЗОН (два спинбокса + стрелка) ───────────────────────
        range_field, range_v = make_field("ДИАПАЗОН, МГц", min_width=260)
        range_row = QHBoxLayout()
        range_row.setSpacing(6)
        range_row.setContentsMargins(0, 0, 0, 0)
        range_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.spin_start_freq = spin_d(24, 1750, self.cfg.start_freq_hz / 1e6, 1.0, 2)
        self.spin_stop_freq  = spin_d(25, 1750, self.cfg.stop_freq_hz  / 1e6, 1.0, 2)
        _arrow = QLabel("→")
        _arrow.setObjectName("SettingsArrow")
        _arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        range_row.addWidget(self.spin_start_freq, 0, Qt.AlignmentFlag.AlignVCenter)
        range_row.addWidget(_arrow, 0, Qt.AlignmentFlag.AlignVCenter)
        range_row.addWidget(self.spin_stop_freq, 0, Qt.AlignmentFlag.AlignVCenter)
        range_v.addLayout(range_row)
        sp.addWidget(range_field)

        self.spin_start_freq.editingFinished.connect(self._clamp_freq_start)
        self.spin_start_freq.valueChanged.connect(self._clamp_freq_start)
        self.spin_stop_freq.editingFinished.connect(self._clamp_freq_stop)
        self.spin_stop_freq.valueChanged.connect(self._clamp_freq_stop)

        # ── ПОРОГ ─────────────────────────────────────────────────────
        threshold_field, threshold_v = make_field("ПОРОГ, дБ", 110)
        self.spin_threshold = spin_d(1.0, 40.0, self.cfg.threshold_db, 0.5, 1)
        threshold_v.addWidget(self.spin_threshold)
        sp.addWidget(threshold_field)

        # ── УСИЛЕНИЕ ──────────────────────────────────────────────────
        gain_field, gain_v = make_field("УСИЛ. SDR, дБ", 110)
        self.spin_gain = spin_d(0.0, 50.0, self.cfg.sdr_gain_db, 0.5, 1)
        gain_v.addWidget(self.spin_gain)
        sp.addWidget(gain_field)

        # ── AVG ───────────────────────────────────────────────────────
        avg_field, avg_v = make_field("УСРЕДНЕНИЙ", 100)
        self.spin_avg = QSpinBox()
        self.spin_avg.setRange(1, 100)
        self.spin_avg.setValue(self.cfg.averaging_count)
        avg_v.addWidget(self.spin_avg)
        sp.addWidget(avg_field)

        sp.addStretch(1)

        # ── Чекбоксы ──────────────────────────────────────────────────
        self.chk_maxhold = QCheckBox("Уд. максимума")
        self.chk_maxhold.setChecked(self.cfg.use_max_hold)
        sp.addWidget(self.chk_maxhold)

        sp.addSpacing(16)

        self.chk_lock_bw = QCheckBox("Фикс. полосу")
        self.chk_lock_bw.setChecked(True)
        self.chk_lock_bw.setToolTip(
            "В live-режиме зафиксировать ширину полосы SDR.\n"
            "Разрешён только пан. Предотвращает лаги."
        )
        sp.addWidget(self.chk_lock_bw)
        sp.addSpacing(4)

        self._settings_widgets = [
            self.spin_start_freq, self.spin_stop_freq, self.spin_threshold,
            self.spin_gain, self.spin_avg, self.chk_maxhold, self.chk_lock_bw,
        ]
        return box

    def _create_remote_panel(self) -> QWidget:
        """Панель удалённого управления в сайдбаре."""
        self._remote_box = QWidget()
        v = QVBoxLayout(self._remote_box)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(14)

        # ── Секция: Режим ──────────────────────────────────────────────
        sec_mode = QLabel("РЕЖИМ")
        sec_mode.setObjectName("SidebarSection")
        v.addWidget(sec_mode)

        self._combo_mode = QComboBox()
        self._combo_mode.addItem("Ручной",             "manual")
        self._combo_mode.addItem("Полуавтоматический", "semi_auto")
        self._combo_mode.addItem("Автоматический",     "auto")
        self._combo_mode.setToolTip(
            "<b>Ручной</b> — оператор включает/выключает тест вручную, клиент не нужен.<br>"
            "<b>Полуавтоматический</b> — оператор нажимает кнопки на детекторе,<br>"
            "тест включается/выключается автоматически через сеть.<br>"
            "<b>Автоматический</b> — детектор управляет всем самостоятельно,<br>"
            "участие оператора не требуется."
        )
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        v.addWidget(self._combo_mode)

        # ── Секция: Сервер ─────────────────────────────────────────────
        from PyQt6.QtWidgets import QFormLayout
        sec_server = QLabel("СЕРВЕР")
        sec_server.setObjectName("SidebarSection")
        v.addWidget(sec_server)

        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(0, 0, 0, 0)

        self._lbl_remote_addr = QLabel(self._remote_server.local_address)
        self._lbl_remote_addr.setObjectName("MonoValue")

        self._lbl_remote_clients = QLabel("Нет подключений")

        self._spin_settle = QSpinBox()
        self._spin_settle.setRange(100, 5000)
        self._spin_settle.setValue(500)
        self._spin_settle.setSuffix(" мс")
        self._spin_settle.setToolTip(
            "Рекомендуется ≥500 мс при Ethernet, ≥1000 мс при WiFi."
        )

        form.addRow("Адрес:",   self._lbl_remote_addr)
        form.addRow("Клиенты:", self._lbl_remote_clients)
        form.addRow("Буфер:",   self._spin_settle)
        v.addLayout(form)

        v.addStretch(1)
        return self._remote_box

    @property
    def _FREQ_BW_MHZ(self) -> float:
        """Полоса одного захвата текущего бэкенда в МГц (RTL-SDR: 2, HackRF: 10)."""
        return self._live_bw_hz / 1e6

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
        self._action_bar.setVisible(not fullscreen)
        self._settings_panel.setVisible(not fullscreen)
        self._sidebar.setVisible(not fullscreen)
        # Синхронизируем кнопку в обоих виджетах без повторного эмита
        for w in (self.plot, self.live_widget, self.zero_span_widget):
            w.btn_fullscreen.blockSignals(True)
            w.btn_fullscreen.setChecked(fullscreen)
            w.btn_fullscreen.blockSignals(False)

    # ------------------------------------------------------------------
    # Управление процессом
    # ------------------------------------------------------------------
    def _on_live_stop_requested(self) -> None:
        """Кнопка ■ на live_widget: замораживаем график, сессия SDR сохраняется."""
        if self.current_step == "live_preview":
            self._stop_panorama_preview()
            # self.ctrl.close() УБРАН → устройство остается подключенным
            self.live_widget.set_live_running(False)
            self.btn_action.setText("ЗАПУСТИТЬ ИЗМЕРЕНИЕ ПАНОРАМЫ")
            self.btn_action.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.lbl_instruction.setText(
                "<b>Прямой эфир остановлен</b><br>"
                "<span style='color:#aaa'>"
                "График заморожен. Сессия SDR сохранена.<br>"
                "Нажмите «Возобновить» для мгновенного продолжения или «СБРОС» для полного отключения.</span>"
            )
        else:
            self._reset_to_start()

    def _on_live_resume_requested(self) -> None:
        """Кнопка ▶ на live_widget: перезапускает захват без переподключения."""
        if not self._apply_settings_to_cfg():
            return
        # Устройство уже подключено и сконфигурировано → просто запускаем поток
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
        self.btn_action.setEnabled(False)
        self._settle_timer.stop()

        self._stop_panorama_preview()
        # restore_config=False: SDR всё равно будет закрыт, восстанавливать конфиг не нужно
        # (попытка configure() во время reset вызывает ошибки USB -9/-6 в librtlsdr)
        self._stop_zero_span(restore_config=False)
        if self.wf:
            self.wf.stop()

        if self.thread is not None and self.thread.isRunning():
            self.thread.wait(10_000)

        # ✅ Явно закрываем SDR, чтобы погасить диод RX
        if self.ctrl and getattr(self.ctrl, 'is_connected', False):
            self.ctrl.close()

        self._do_ui_reset()
        self._update_hw_limits()

    def _on_control_button_clicked(self):
        if self.current_step in ("idle", "expert"):
            if self.scan_mode == "demo":
                self._load_measurement()
            else:
                self._connect_and_start()
        elif self.current_step == "live_preview":
            self._launch_measurement_from_preview()
            return
        else:
            # Если ZeroSpan активен — освободить SDR до того, как workflow
            # начнёт захват (два потока не могут использовать устройство одновременно).
            if self._zs_worker is not None or self._spectrum_stack.currentIndex() == 1:
                self._on_zero_span_stop()

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
                    self.lbl_instruction.setText("Выполнение измерения...")
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
                f"<b>Тест {label} — стабилизация {settle_ms} мс...</b><br>"
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
        self.lbl_instruction.setText("Выполнение измерения...")
        self.btn_stop.setEnabled(True)

    # ------------------------------------------------------------------

    def _connect_and_start(self):
        # ZeroSpan занимает SDR в узкой полосе — освободить до нового захвата.
        # restore_config=False: SDR будет перенастроен для панорамы в этом же вызове.
        if self._zs_worker is not None or self._spectrum_stack.currentIndex() == 1:
            self._stop_zero_span(restore_config=False)
            self._zs_freq_hz = None
            self.zero_span_widget.set_running(True)
            self._spectrum_stack.setCurrentIndex(0)
            self.expert_panel.set_zero_span_active(False)

        if not self._apply_settings_to_cfg():
            return
        self.cfg.skip_verification = (self.scan_mode == "quick")

        if self.scan_mode == "simulator":
            self._start_simulator()
            return

        try:
            # RTL-SDR: если устройство уже открыто — только переконфигурируем.
            # close() → open() в librtlsdr вызывает повреждение кучи (malloc corruption),
            # потому что внутренние USB-потоки не успевают завершиться.
            if RtlSdrBackend is not None \
                    and isinstance(self.ctrl, RtlSdrBackend) \
                    and self._hw == "rtlsdr" and self.ctrl.is_connected:
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
            elif HackRfBackend is not None \
                    and isinstance(self.ctrl, HackRfBackend) \
                    and self._hw == "hackrf" and self.ctrl.is_connected:
                try:
                    self.ctrl.configure(self.cfg)
                except Exception:
                    self.ctrl.close()
                    self.ctrl = HackRfBackend()
                    self.ctrl.connect()
                    self.ctrl.configure(self.cfg)
            else:
                try:
                    self.ctrl.close()
                except Exception:
                    pass
                self.ctrl = self._make_backend()
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
        if self.cfg.fft_size != 8192:
            cfg.calibration_offset_db += 20.0 * np.log10(self.cfg.fft_size / 8192)
        _LIVE_BW = self._live_bw_hz
        if self.chk_lock_bw.isChecked():
            sender = self.sender()
            if sender is self.spin_start_freq:
                # пользователь изменил начало — сохраняем полосу, двигаем конец
                cfg.stop_freq_hz  = min(self._freq_max_hz, cfg.start_freq_hz + _LIVE_BW)
                cfg.start_freq_hz = cfg.stop_freq_hz - _LIVE_BW
            elif sender is self.spin_stop_freq:
                # пользователь изменил конец — сохраняем полосу, двигаем начало
                cfg.start_freq_hz = max(self._freq_min_hz, cfg.stop_freq_hz - _LIVE_BW)
                cfg.stop_freq_hz  = cfg.start_freq_hz + _LIVE_BW
            else:
                # галка или другой виджет — центрируем окно live BW
                center = (cfg.start_freq_hz + cfg.stop_freq_hz) / 2
                cfg.start_freq_hz = max(self._freq_min_hz, center - _LIVE_BW / 2)
                cfg.stop_freq_hz  = min(self._freq_max_hz, center + _LIVE_BW / 2)
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
        _LIVE_BW = self._live_bw_hz
        if self.chk_lock_bw.isChecked():
            # Фиксированная полоса по центру вида — без sweep и лагов
            center_hz = (start_mhz + stop_mhz) / 2 * 1e6
            cfg.start_freq_hz = max(self._freq_min_hz, center_hz - _LIVE_BW / 2)
            cfg.stop_freq_hz  = min(self._freq_max_hz, center_hz + _LIVE_BW / 2)
            # Спиннеры показывают реальный диапазон SDR, а не диапазон вида
            spin_start = cfg.start_freq_hz / 1e6
            spin_stop  = cfg.stop_freq_hz  / 1e6
        else:
            span_hz = (stop_mhz - start_mhz) * 1e6
            cfg.start_freq_hz = max(self._freq_min_hz, start_mhz * 1e6 - span_hz * 0.05)
            cfg.stop_freq_hz  = min(self._freq_max_hz, stop_mhz  * 1e6 + span_hz * 0.05)
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
        if self.cfg.fft_size != 8192:
            cfg.calibration_offset_db += 20.0 * np.log10(self.cfg.fft_size / 8192)
        self._panorama_preview_worker.update_config(cfg)

    def _on_table_context_menu(self, pos) -> None:
        """Правый клик по строке: удалить сигнал (expert) или метку (preview/idle/фаза1)."""
        is_expert = (self.current_step == "expert")
        phase1_waiting = (
            self.current_step == "waiting" and
            "ФОН ИЗМЕРЕН" in self._current_action_title
        )
        if (self.current_step not in ("live_preview", "idle")
                and not phase1_waiting and not is_expert):
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

        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)

        if is_expert:
            act_del = menu.addAction("Удалить сигнал")
            if menu.exec(self.table.viewport().mapToGlobal(pos)) == act_del:
                self._delete_signal(row)
            return

        # Не экспертный режим — удаляем только метки (закладки)
        is_bookmark = any(abs(f - freq_hz) < 100e3 for f in self._bookmark_freqs_hz)
        if not is_bookmark and self.wf and hasattr(self.wf, "signals"):
            signals = self.wf.signals
            if 0 <= row < len(signals):
                is_bookmark = (signals[row].detection_method == "bookmark")
        if not is_bookmark:
            return
        act_del = menu.addAction("Удалить метку")
        if menu.exec(self.table.viewport().mapToGlobal(pos)) == act_del:
            self._delete_bookmark(freq_hz)

    # ------------------------------------------------------------------
    # Редактирование таблицы
    # ------------------------------------------------------------------

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self.current_step != "expert":
            return
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
                color_hex = self._status_delegate.color_for(text)
                self.table.blockSignals(True)
                item.setForeground(QColor(color_hex))
                self.table.blockSignals(False)
                s.status_color = _StatusDelegate.key_for(text)
                # Перерисовываем маркеры на графике с новым цветом
                if self.wf and hasattr(self.wf, "signals"):
                    self.plot.plot_signals(self.wf.signals)
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
        self.btn_action.setText("ЗАПУСТИТЬ ИЗМЕРЕНИЕ ПАНОРАМЫ")
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
        self.expert_panel.enable_expert_mode(False)

        from copy import copy as _cp
        prev_cfg = _cp(self.cfg)
        prev_cfg.fft_size = 8192
        prev_cfg.averaging_count = 1
        prev_cfg.use_max_hold = False
        if self.cfg.fft_size != 8192:
            prev_cfg.calibration_offset_db += 20.0 * np.log10(self.cfg.fft_size / 8192)
        # При включённой фиксации полосы — ограничиваем SDR hardware-bandwidth,
        # чтобы всегда работал _capture_single без медленного sweep
        _LIVE_BW = self._live_bw_hz
        if self.chk_lock_bw.isChecked():
            center = (prev_cfg.start_freq_hz + prev_cfg.stop_freq_hz) / 2
            prev_cfg.start_freq_hz = max(self._freq_min_hz, center - _LIVE_BW / 2)
            prev_cfg.stop_freq_hz  = min(self._freq_max_hz, center + _LIVE_BW / 2)
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

        self._set_status(
            "Прямой эфир",
            "Параметры можно менять в реальном времени. Поставьте метки, затем нажмите «Запустить».",
            icon="↻",
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
        self._set_status("Запуск", "Инициализация измерения...", icon="↻")
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
        self.expert_panel.enable_expert_mode(False)

        self.plot.clear()
        # Показываем метки в таблице пока идёт фаза 1 (до обнаружения сигналов)
        self.wf = None
        self._refresh_bookmark_table()

        self.wf = self._make_workflow()
        self.wf.on_test_activate = self._on_test_activate
        # Автоматический режим: workflow сам переключает фазы без участия оператора
        if self._control_mode == "auto" and self._should_auto_control_test():
            self.wf.auto_settle_s = self._spin_settle.value() / 1000.0
            if self._remote_server.client_count > 0:
                self.wf.wait_for_client_ready = self._remote_server.wait_for_acks
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
        # Кнопки меток на этапе 1 — только если включён экспертный режим
        self.plot.set_mark_buttons_visible(self.act_expert_mode.isChecked())

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
        # Таблица строится в том же порядке, что и signals — row == index в списке
        idx = row
        if not (0 <= idx < len(signals)):
            self.plot.clear_highlight()
            self.expert_panel.clear_signal()
            return
        sig = signals[idx]
        if _marker_color(sig) is not None:
            freq_mhz = sig.frequency_hz / 1e6
            self.plot.set_highlight(freq_mhz)
            self.plot.pan_to(freq_mhz)
        else:
            self.plot.clear_highlight()
        self.expert_panel.set_signal(sig, idx)
        self._refresh_sidebar_tab_titles()
        # Автопереключение убрано — бейдж с частотой на табе Эксперт
        # показывает оператору, какой сигнал загружен. Переход — по
        # двойному клику (см. _on_table_double_clicked).

    def _on_table_double_clicked(self, _item) -> None:
        """Двойной клик по строке таблицы → переход в Эксперт-таб."""
        if True or self.expert_panel._signal is not None:
            self._sidebar.setCurrentIndex(2)

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
        self._zs_freq_hz = freq_hz
        self.zero_span_widget.clear()
        self.zero_span_widget.set_signal_info(freq_hz)
        self.zero_span_widget.set_running(True)
        self._spectrum_stack.setCurrentIndex(1)
        self._zs_start_worker(freq_hz)
        self.expert_panel.enable_remeasure(False)

    def _zs_start_worker(self, freq_hz: float) -> None:
        from copy import copy
        self._zs_worker = ZeroSpanWorker(self.ctrl, copy(self.cfg), freq_hz)
        self._zs_worker.amplitude_updated.connect(self.zero_span_widget.add_point)
        self._zs_worker.amplitude_updated.connect(self._audio.set_amplitude)
        self._zs_worker.error.connect(self._on_zero_span_error)
        self._zs_worker.start()

    def _on_zs_pause(self) -> None:
        """Заморозить график: остановить воркер, остаться в zero span виде."""
        if self._zs_worker is not None:
            self._zs_worker.stop()
            self._zs_worker.wait(5000)
            self._zs_worker = None
        self._audio.stop()

    def _on_zs_resume(self) -> None:
        """Возобновить захват с той же частотой."""
        if self._zs_freq_hz is None or self._zs_worker is not None:
            return
        self._zs_start_worker(self._zs_freq_hz)

    def _on_zs_audio_toggle(self, active: bool) -> None:
        if active:
            self._audio.start()
        else:
            self._audio.stop()

    def _on_zero_span_stop(self) -> None:
        self._stop_zero_span()
        self._zs_freq_hz = None
        self.zero_span_widget.set_running(True)   # сброс кнопок для следующего запуска
        self._spectrum_stack.setCurrentIndex(0)
        self.expert_panel.set_zero_span_active(False)
        if self.current_step in ("idle", "expert"):
            self.expert_panel.enable_remeasure(True)

    def _on_zero_span_error(self, msg: str) -> None:
        self._stop_zero_span()
        if self._is_device_lost(msg):
            self._on_sdr_error(msg)
        else:
            self._spectrum_stack.setCurrentIndex(0)
            self.expert_panel.set_zero_span_active(False)
            QMessageBox.warning(self, "Мониторинг частоты", f"Ошибка измерения:\n{msg}")

    def _stop_zero_span(self, restore_config: bool = True) -> None:
        if self._zs_worker is not None:
            self._zs_worker.stop(restore_config=restore_config)
            self._zs_worker.wait(5000)
            self._zs_worker = None
        self._audio.stop()

    def _signal_by_freq(self, freq_hz: float):
        signals = self.wf.signals if self.wf and hasattr(self.wf, "signals") else []
        if not signals:
            return None
        return min(signals, key=lambda s: abs(s.frequency_hz - freq_hz))

    def _on_expert_signal_modified(self, idx: int) -> None:
        signals = self.wf.signals if self.wf and hasattr(self.wf, "signals") else []
        if not signals:
            return
        if 0 <= idx < len(signals):
            sig = signals[idx]
            # Для ручных сигналов — пересчитать статус на основе порога
            # (автоматически, чтобы оператор видел подсказку после переизмерения)
            if sig.detection_method == "manual" and sig.amplitude_on_db != 0.0:
                if sig.amplitude_diff_db >= self.cfg.threshold_db:
                    sig.status_color = "yellow"   # выше порога — требует проверки
                else:
                    sig.status_color = "red"      # ниже порога — не подтверждён
            self.plot.set_highlight(sig.frequency_hz / 1e6)
        self._update_table_from_signals(signals)
        self.plot.plot_signals(signals)
        # Восстановить выделение строки — rebuild таблицы сбрасывает selection
        if 0 <= idx < self.table.rowCount():
            self.table.selectRow(idx)

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
            f"<b>Архив загружен</b><br>"
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
            f"<b>Режим сравнения</b><br>"
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

        t = self._theme
        if "ЗАВЕРШЕНА" in title or "ЗАВЕРШЕНО" in title:
            title_color = t["tbl_status_ok"]
        elif "ОШИБКА" in title or "СТОП" in title:
            title_color = t["tbl_status_fail"]
        else:
            title_color = t["text_dim"]

        # Двухстрочный статус: заголовок фазы + описание
        self._lbl_status_title.setText(title.upper())
        self._lbl_status_title.setStyleSheet(
            f"color: {title_color}; font-size: 10px; letter-spacing: 0.08em;"
        )
        # Описание — простой текст без HTML-обёртки
        plain_instruction = instruction.replace(chr(10), " ").strip()
        self.lbl_instruction.setText(plain_instruction)
        self.btn_action.setText(btn_text)
        self.btn_action.setEnabled(True)
        self.btn_stop.setEnabled(True)

        # CSV/NPZ включаются только в экспертном режиме (_enter_expert_mode)

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
        # После сброса — стартовый экран (idle). Кнопки меток видны только в эксперт. режиме.
        self.plot.set_mark_buttons_visible(self.act_expert_mode.isChecked())
        self.live_widget.set_mark_available(False)
        self.table.setRowCount(0)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._reset_progress()
        self._stop_zero_span(restore_config=False)
        self.live_widget.clear()
        self.live_widget.highlight_mark(None)
        self._spectrum_stack.setCurrentIndex(0)
        self.expert_panel.clear_signal()
        self.expert_panel.set_zero_span_active(False)
        self.expert_panel.enable_remeasure(False)
        self.expert_panel.enable_expert_mode(False)

        self._set_status("Готов", "Подключите SDR для начала работы.")
        self._set_scan_mode(self.scan_mode)   # восстанавливает текст кнопки
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
        """Пользователь поставил метку на панораме."""
        freq_hz = freq_mhz * 1e6
        if self.current_step == "expert":
            # Экспертный режим: метка создаёт новый сигнал для проверки.
            # remove_panorama_mark вызывается ВСЕГДА — даже если _add_expert_signal
            # вернулся рано из-за дубликата, иначе оранжевая метка останется сиротой.
            self._add_expert_signal(freq_hz)
            self.plot.remove_panorama_mark(freq_mhz)
            return
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
        self.prog.setVisible(True)
        self._prog_anim.stop()
        self._prog_anim.setStartValue(self.prog.value())
        self._prog_anim.setEndValue(value)
        self._prog_anim.start()

    def _reset_progress(self) -> None:
        """Мгновенно сбрасывает прогрессбар в 0, останавливая текущую анимацию."""
        self._prog_anim.stop()
        self.prog.setValue(0)
        self.prog.setVisible(False)

    def _on_thread_finished(self):
        # Вызывается только при нормальном завершении (при сбросе — отключается в _do_ui_reset)
        self.btn_stop.setEnabled(True)
        self._set_settings_enabled(True)
        self.btn_action.setText("НОВЫЙ ПОИСК")
        n = self.table.rowCount()
        self._set_status(
            "Измерение завершено",
            f"Обнаружено {n} сигнал{'ов' if n == 0 or n >= 5 else 'а' if n > 1 else ''}. Выберите строку для анализа.",
            icon="◎",
        )
        if self.act_expert_mode.isChecked():
            self.current_step = "expert"
            self._enter_expert_mode()
        else:
            self.current_step = "idle"
            self.expert_panel.enable_remeasure(True)
        self._reset_progress()

    # ------------------------------------------------------------------
    # Экспертный режим (после завершения всех измерений)
    # ------------------------------------------------------------------

    def _on_expert_mode_toggled(self, checked: bool) -> None:
        """Реакция на включение/выключение «Экспертного режима» в меню."""
        # Показать/скрыть вкладку «Экспертный анализ»
        self._sidebar.tabBar().setTabVisible(2, checked)
        if not checked and self._sidebar.currentIndex() == 2:
            self._sidebar.setCurrentIndex(0)
        # Кнопки меток — только в экспертном режиме
        if self.current_step == "live_preview":
            # Во время предпросмотра — live_widget
            self.live_widget.set_mark_available(checked)
        elif self.current_step == "idle":
            # Стартовый экран (spectrum_widget до первого измерения)
            self.plot.set_mark_buttons_visible(checked)
        if checked:
            # Если измерение уже завершено — войти в эксперт-режим немедленно
            if (self.current_step == "idle" and self.wf
                    and hasattr(self.wf, "signals") and self.wf.signals):
                self.current_step = "expert"
                self._enter_expert_mode()
        else:
            if self.current_step == "expert":
                self._exit_expert_mode()
        # Switch sidebar tab to Expert when enabled with signal selected, else Results
        if checked and self.table.selectedItems():
            self._sidebar.setCurrentIndex(2)

    def _exit_expert_mode(self) -> None:
        """Выйти из экспертного режима без сброса результатов измерения."""
        self.current_step = "idle"
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.act_save.setEnabled(False)
        self.expert_panel.enable_expert_mode(False)
        self.plot.set_mark_buttons_visible(False)
        self.live_widget.set_mark_available(False)

    def _enter_expert_mode(self) -> None:
        """Включить экспертный режим: редактирование таблицы, метки, удаление, CSV."""
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked |
            QTableWidget.EditTrigger.EditKeyPressed
        )
        self.act_save.setEnabled(True)
        self.act_export_spectrum.setEnabled(self._last_on is not None)
        self.expert_panel.enable_remeasure(True)
        self.expert_panel.enable_expert_mode(True)
        self.expert_panel.set_threshold(self.cfg.threshold_db)
        # Кнопки меток — только в экспертном режиме
        self.plot.set_mark_buttons_visible(True)
        self.live_widget.set_mark_available(True)
        # Обновляем таблицу, чтобы она работала с новыми триггерами
        if self.wf and hasattr(self.wf, "signals") and self.wf.signals:
            self._update_table_from_signals(self.wf.signals)

    def _add_expert_signal(self, freq_hz: float) -> None:
        """Создать новый сигнал по метке оператора и добавить в таблицу."""
        if not (self.wf and hasattr(self.wf, "signals")):
            return
        if any(abs(s.frequency_hz - freq_hz) < 100e3 for s in self.wf.signals):
            return
        amp_on = amp_off = 0.0
        if self._last_on is not None:
            idx = int(np.searchsorted(self._last_on.frequencies_hz, freq_hz))
            idx = max(0, min(idx, len(self._last_on.amplitudes_db) - 1))
            amp_on = float(self._last_on.amplitudes_db[idx])
        if self._last_off is not None:
            idx = int(np.searchsorted(self._last_off.frequencies_hz, freq_hz))
            idx = max(0, min(idx, len(self._last_off.amplitudes_db) - 1))
            amp_off = float(self._last_off.amplitudes_db[idx])
        rbw = self._last_on.rbw_hz if self._last_on else 0.0
        sig = PEMINSignal(
            frequency_hz=freq_hz,
            amplitude_on_db=amp_on,
            amplitude_off_db=amp_off,
            amplitude_diff_db=amp_on - amp_off,
            rbw_hz=rbw,
            detection_method="manual",
            verified_1=None,
            verified_2=None,
        )
        self.wf.signals.append(sig)
        self._update_table_from_signals(self.wf.signals)
        self.plot.plot_signals(self.wf.signals)

    def _delete_signal(self, row: int) -> None:
        """Удалить сигнал по индексу строки из таблицы и графика."""
        if not (self.wf and hasattr(self.wf, "signals")):
            return
        signals = self.wf.signals
        if row < 0 or row >= len(signals):
            return
        sig = signals.pop(row)
        self._bookmark_freqs_hz = [
            f for f in self._bookmark_freqs_hz if abs(f - sig.frequency_hz) >= 100e3
        ]
        self.plot.remove_panorama_mark(sig.frequency_hz / 1e6)
        self.expert_panel.clear_signal()
        self.live_widget.highlight_mark(None)
        self.plot.clear_highlight()
        self._update_table_from_signals(signals)
        self.plot.plot_signals(signals)

    def _on_expert_delete_requested(self) -> None:
        """Обработчик кнопки «Удалить сигнал» из expert_panel."""
        if not (self.wf and hasattr(self.wf, "signals")):
            return
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        if row < 0 or row >= len(self.wf.signals):
            return
        sig = self.wf.signals[row]
        reply = QMessageBox.question(
            self, "Удалить сигнал",
            f"Удалить {sig.frequency_hz / 1e6:.4f} МГц из таблицы?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._delete_signal(row)

    # ------------------------------------------------------------------
    # Удалённое управление тестовым клиентом
    # ------------------------------------------------------------------

    @property
    def _control_mode(self) -> str:
        """Текущий режим: 'manual' | 'semi_auto' | 'auto'."""
        return self._combo_mode.currentData()

    def _on_mode_changed(self, _: int) -> None:
        mode = self._control_mode
        enabled = (mode != "manual")
        self._spin_settle.setEnabled(enabled)
        self._lbl_settle.setEnabled(enabled)
        self._remote_server.set_mode(mode)

    def _on_remote_client_count(self, count: int) -> None:
        # Вызывается из фонового потока — emit через signal безопасен
        self._remote_count_signal.emit(count)

    def _update_remote_status(self, count: int) -> None:
        self._lbl_remote_addr.setText(self._remote_server.local_address)
        addr = self._remote_server.local_address
        # strip protocol prefix for pill display
        ip = addr.split("//")[-1] if "//" in addr else addr
        if count == 0:
            self._lbl_remote_clients.setText("Нет подключений")
            self._lbl_remote_clients.setStyleSheet(
                f"color: {self._theme['clients_off']};"
            )
            self._pill_clients.setText("● Нет клиентов")
            self._pill_clients.setStyleSheet(
                f"QLabel#AppPill {{ color: {self._theme['text_muted']}; font-size: 12px;"
                f" padding: 4px 10px; border-radius: 999px;"
                f" background: {self._theme['bg_input']}; border: 1px solid {self._theme['border']}; }}"
            )
        else:
            noun = "клиент" if count == 1 else ("клиента" if count < 5 else "клиентов")
            self._lbl_remote_clients.setText(f"{count} {noun}")
            self._lbl_remote_clients.setStyleSheet("color:#66BB6A;")
            self._pill_clients.setText(f"● {count} {noun} · {ip}")
            self._pill_clients.setStyleSheet(
                f"QLabel#AppPill {{ color: {self._theme['tbl_status_ok']}; font-size: 12px;"
                f" padding: 4px 10px; border-radius: 999px;"
                f" background: {self._theme['bg_input']}; border: 1px solid {self._theme['border']}; }}"
            )

    def _on_test_activate(self, active: bool) -> None:
        """Активирует/деактивирует тест: DemoSimulator + remote clients."""
        if isinstance(self.ctrl, DemoSimulator):
            self.ctrl.test_active = active
        if active:
            self._remote_server.send_test_start()
        else:
            self._remote_server.send_test_stop()

    def closeEvent(self, event) -> None:
        # 1. Отменяем буферизацию и таймеры
        self._settle_timer.stop()
        
        # 2. Останавливаем Live-просмотр (отключает хендлеры настроек + LiveWorker)
        self._stop_panorama_preview()
        
        # 3. Останавливаем ZeroSpan и аудио-монитор
        self._stop_zero_span()
        
        # 4. Останавливаем основной поток измерения
        if self.thread is not None and self.thread.isRunning():
            self.thread.wait(2000)  # 2 сек на graceful shutdown
            
        # 5. Останавливаем сервер удалённого управления
        self._remote_server.stop()
        
        # 6. КОРРЕКТНО закрываем SDR-бэкенд.
        # HackRF: вызывает _stop_streaming() → hackrf_stop_rx() → hackrf_close() → hackrf_exit()
        # RTL-SDR: вызывает rtlsdr_close()
        if hasattr(self, 'ctrl') and self.ctrl is not None:
            try:
                self.ctrl.close()
            except Exception as e:
                print(f"⚠️ Ошибка при отключении SDR: {e}")
                
        # 7. Завершаем Qt-приложение
        super().closeEvent(event)

    def _plot_data(self, on, off, diff):
        self._last_on = on
        self._last_off = off
        self._last_diff = diff
        f_mhz = on.frequencies_hz / 1e6
        x_min, x_max = float(f_mhz.min()), float(f_mhz.max())

        self.plot.clear()
        # Скрываем кнопки меток — метки уже переданы в workflow, дальше они не нужны
        self.plot.set_mark_buttons_visible(False)
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

    def _refresh_table_colors(self) -> None:
        """Перекрасить ячейки статуса в таблице под текущую тему без пересборки строк."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 5)
            if item:
                item.setForeground(
                    QColor(self._status_delegate.color_for(item.text()))
                )

    # ------------------------------------------------------------------
    # Таблица результатов
    # ------------------------------------------------------------------

    def _update_table_from_signals(self, signals):
        COLOR_WAIT     = self._theme["tbl_status_wait"]
        COLOR_SUCCESS  = self._theme["tbl_status_ok"]
        COLOR_FAIL_V1  = self._theme["tbl_status_fail"]
        COLOR_EXTERNAL = self._theme["tbl_status_ext"]
        COLOR_WARN     = self._theme["tbl_status_warn"]

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
                item_status = QTableWidgetItem("Потенциальный")
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
                    status_text = f"ПЭМИН ({s.harmonic_count} гарм.)"
                    color_hex = COLOR_SUCCESS
                elif s.status_color == "yellow":
                    status_text = f"Неопределённо ({s.harmonic_count} гарм.)"
                    color_hex = COLOR_WARN
                else:
                    status_text = "Гармоник нет"
                    color_hex = COLOR_FAIL_V1
            else:
                color_map = {
                    "yellow": (COLOR_WARN,     "В1 OK"),
                    "green":  (COLOR_SUCCESS,  "ПЭМИН"),
                    "red":    (COLOR_FAIL_V1,  "Брак (В1)"),
                    "blue":   (COLOR_EXTERNAL, "Внешний / Двойной брак"),
                }
                v1 = s.verified_1
                v2 = s.verified_2
                # Для ручных сигналов оператор задаёт статус напрямую через dropdown;
                # verification flags не используем — иначе статус сбрасывается при rebuild
                if s.detection_method == "manual":
                    if s.status_color == "yellow":
                        # Ещё не верифицирован оператором — показываем как потенциальный
                        status_text = "Потенциальный"
                        color_hex   = COLOR_WARN
                    else:
                        color_hex, status_text = color_map.get(
                            s.status_color, (COLOR_WAIT, "Ожидание")
                        )
                        if s.status_color == "blue":
                            status_text = "Внешний / Двойной брак"
                elif v1 is None and v2 is None:
                    status_text = "Ожидание"
                    color_hex = COLOR_WAIT
                elif v1 is not None and v2 is None:
                    if v1:
                        status_text = "В1 OK"
                        color_hex = COLOR_WARN
                    else:
                        status_text = "Брак (В1)"
                        color_hex = COLOR_FAIL_V1
                else:
                    color_hex, status_text = color_map.get(
                        s.status_color, (COLOR_WAIT, "—")
                    )
                    if s.status_color == "blue":
                        status_text = "Внешний (В2)" if (v1 and not v2) else "Двойной брак"

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
