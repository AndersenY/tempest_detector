"""
Компактная экспертная панель (фаза 4 редизайна).

Сохраняет публичный API оригинала:
  - сигналы: signal_modified, zero_span_started, zero_span_stopped, delete_requested
  - методы:  set_signal, clear_signal, set_instrument, enable_remeasure,
             enable_expert_mode, set_threshold, set_zero_span_active, apply_theme

Визуальные изменения:
  • Карточка «выбранный сигнал» сверху — большая частота + статус-чип
  • Блок readout: Сигнал / Шум / Δ в три колонки
  • Кнопки переизмерения: 3 в ряд (Сигнал, Шум, Частоту)
  • «Вручную» отдельной строкой
  • Zero Span + аудио одной кнопкой
  • Удалить — внизу, только в экспертном режиме
"""

import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QInputDialog, QMessageBox, QProgressBar, QFrame,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from core.backends import BaseInstrument
from core.models import PEMINSignal
from core.signal_processor import find_peak_in_window
from gui.theme import DARK


# ---------------------------------------------------------------------------
# Фоновый поток переизмерения (без изменений из оригинала).
# ---------------------------------------------------------------------------

class _RemeasureWorker(QThread):
    done  = pyqtSignal(float, float)   # (freq_hz, amp_db) — лучший результат
    error = pyqtSignal(str)

    def __init__(self, ctrl: BaseInstrument, sig: PEMINSignal,
                 mode: str, n: int = 5) -> None:
        super().__init__()
        self._ctrl = ctrl
        self._sig  = sig
        self._mode = mode   # "signal" | "noise" | "peak"
        self._n    = n

    def run(self) -> None:
        try:
            window_hz = max(self._sig.rbw_hz * 20, 50_000)
            best_amp  = -np.inf
            best_freq = self._sig.frequency_hz
            for _ in range(self._n):
                spec  = self._ctrl.capture_spectrum()
                f, a  = find_peak_in_window(spec, self._sig.frequency_hz, window_hz)
                if a > best_amp:
                    best_amp  = a
                    best_freq = f
            self.done.emit(best_freq, best_amp)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# ExpertPanel — компактная версия.
# ---------------------------------------------------------------------------

class ExpertPanel(QWidget):
    """
    Компактная панель экспертного анализа.

    Сохраняет публичный API исходного ExpertPanel — снаружи поведение
    идентичное, изменилась только раскладка.
    """

    # ── Public signals ────────────────────────────────────────────────
    signal_modified   = pyqtSignal(int)
    zero_span_started = pyqtSignal(float)
    zero_span_stopped = pyqtSignal()
    delete_requested  = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._theme = DARK

        self._signal: PEMINSignal | None = None
        self._signal_idx: int = -1
        self._ctrl: BaseInstrument | None = None
        self._worker: _RemeasureWorker | None = None
        self._expert_mode: bool = False
        self._threshold_db: float | None = None

        self._init_ui()
        self._update_display()
        self.apply_theme(self._theme)

    # ==================================================================
    # UI
    # ==================================================================

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Карточка выбранного сигнала ───────────────────────────────
        self._signal_card = QFrame()
        self._signal_card.setObjectName("ExpertSignalCard")
        card_layout = QHBoxLayout(self._signal_card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)

        card_text = QVBoxLayout()
        card_text.setSpacing(2)
        card_text.setContentsMargins(0, 0, 0, 0)

        self._lbl_freq = QLabel("—")
        self._lbl_freq.setObjectName("ExpertFreq")
        self._lbl_caption = QLabel("выберите сигнал в Результатах")
        self._lbl_caption.setObjectName("ExpertCaption")

        card_text.addWidget(self._lbl_freq)
        card_text.addWidget(self._lbl_caption)
        card_layout.addLayout(card_text, 1)

        self._lbl_status = QLabel("")
        self._lbl_status.setObjectName("ExpertStatusChip")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_status.setMinimumWidth(72)
        card_layout.addWidget(self._lbl_status, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addWidget(self._signal_card)

        # ── Readout: Сигнал / Шум / Δ в три колонки ──────────────────
        self._readout = QFrame()
        self._readout.setObjectName("ExpertReadout")
        readout_grid = QGridLayout(self._readout)
        readout_grid.setContentsMargins(10, 8, 10, 8)
        readout_grid.setHorizontalSpacing(12)
        readout_grid.setVerticalSpacing(2)

        self._lbl_sig_k = QLabel("СИГНАЛ"); self._lbl_sig_k.setObjectName("ReadoutKey")
        self._lbl_sh_k  = QLabel("ШУМ");    self._lbl_sh_k.setObjectName("ReadoutKey")
        self._lbl_d_k   = QLabel("Δ ДБ");   self._lbl_d_k.setObjectName("ReadoutKey")

        self._lbl_sig_v = QLabel("—"); self._lbl_sig_v.setObjectName("ReadoutVal")
        self._lbl_sh_v  = QLabel("—"); self._lbl_sh_v.setObjectName("ReadoutVal")
        self._lbl_d_v   = QLabel("—"); self._lbl_d_v.setObjectName("ReadoutVal")

        readout_grid.addWidget(self._lbl_sig_k, 0, 0)
        readout_grid.addWidget(self._lbl_sh_k,  0, 1)
        readout_grid.addWidget(self._lbl_d_k,   0, 2)
        readout_grid.addWidget(self._lbl_sig_v, 1, 0)
        readout_grid.addWidget(self._lbl_sh_v,  1, 1)
        readout_grid.addWidget(self._lbl_d_v,   1, 2)
        root.addWidget(self._readout)

        # ── Подсказка экспертного режима ──────────────────────────────
        self._lbl_hint = QLabel("")
        self._lbl_hint.setWordWrap(True)
        self._lbl_hint.setObjectName("ExpertHint")
        root.addWidget(self._lbl_hint)

        # ── Прогресс переизмерения ────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        root.addWidget(self._progress)

        # ── Секция: Переизмерить ──────────────────────────────────────
        self._sec_remeasure = QLabel("ПЕРЕИЗМЕРИТЬ")
        self._sec_remeasure.setObjectName("ExpertSection")
        root.addWidget(self._sec_remeasure)

        remeasure_row = QGridLayout()
        remeasure_row.setSpacing(6)
        remeasure_row.setColumnStretch(0, 1)
        remeasure_row.setColumnStretch(1, 1)
        remeasure_row.setColumnStretch(2, 1)

        self._btn_essh   = QPushButton("♪ Сигнал")
        self._btn_esh    = QPushButton("♪ Шум")
        self._btn_peak   = QPushButton("⊕ Частоту")
        for b, tip, mode in (
            (self._btn_essh, "Переизмерить уровень сигнала (устройство включено)", "signal"),
            (self._btn_esh,  "Переизмерить уровень фонового шума (устройство выключено)", "noise"),
            (self._btn_peak, "Найти точный максимум из 5 захватов в окне ±10·RBW", "peak"),
        ):
            b.setObjectName("ExpertBtn")
            b.setToolTip(tip)
            b.clicked.connect(lambda _, m=mode: self._start_remeasure(m))

        self._btn_manual = QPushButton("Задать вручную…")
        self._btn_manual.setObjectName("ExpertBtn")
        self._btn_manual.setToolTip("Вручную задать уровень сигнала")
        self._btn_manual.clicked.connect(self._set_manual_amplitude)

        remeasure_row.addWidget(self._btn_essh,   0, 0)
        remeasure_row.addWidget(self._btn_esh,    0, 1)
        remeasure_row.addWidget(self._btn_peak,   0, 2)
        remeasure_row.addWidget(self._btn_manual, 1, 0, 1, 3)
        root.addLayout(remeasure_row)

        # ── Секция: Наблюдение ────────────────────────────────────────
        self._sec_watch = QLabel("НАБЛЮДЕНИЕ")
        self._sec_watch.setObjectName("ExpertSection")
        root.addWidget(self._sec_watch)

        self._btn_zero_span = QPushButton("▷ Zero Span + ♪ Аудио")
        self._btn_zero_span.setObjectName("ExpertBtn")
        self._btn_zero_span.setCheckable(True)
        self._btn_zero_span.setToolTip(
            "Непрерывный мониторинг амплитуды на выбранной частоте.\n"
            "Линия уровня во времени + аудио-тон для поиска максимума ИИ."
        )
        self._btn_zero_span.clicked.connect(self._toggle_zero_span)
        root.addWidget(self._btn_zero_span)

        # ── Удаление сигнала (только в экспертном режиме) ────────────
        self._btn_delete = QPushButton("Удалить сигнал из таблицы")
        self._btn_delete.setObjectName("ExpertDeleteBtn")
        self._btn_delete.setToolTip("Удалить выбранный сигнал из таблицы и графика")
        self._btn_delete.clicked.connect(self.delete_requested)
        self._btn_delete.setVisible(False)
        root.addWidget(self._btn_delete)

        root.addStretch(1)

    # ==================================================================
    # Theme
    # ==================================================================

    def apply_theme(self, t: dict) -> None:
        self._theme = t
        # Карточка выбранного сигнала
        self._signal_card.setStyleSheet(
            f"#ExpertSignalCard {{ background: {t['bg_window']};"
            f" border: 1px solid {t['btn_active']}; border-radius: 8px;"
            f" border-left: 3px solid {t['btn_active']}; }}"
            f" #ExpertFreq {{ color: {t['text']}; font-size: 16px; font-weight: 600;"
            f" font-family: monospace; }}"
            f" #ExpertCaption {{ color: {t['text_muted']}; font-size: 10px; }}"
            f" #ExpertStatusChip {{ font-size: 10px; font-weight: 600;"
            f" padding: 3px 10px; border-radius: 4px; }}"
        )
        # Readout-блок
        self._readout.setStyleSheet(
            f"#ExpertReadout {{ background: {t['bg_widget']};"
            f" border: 1px solid {t['border']}; border-radius: 6px; }}"
            f" #ReadoutKey {{ color: {t['text_muted']}; font-size: 9px;"
            f" letter-spacing: 0.06em; }}"
            f" #ReadoutVal {{ color: {t['text']}; font-size: 13px;"
            f" font-family: monospace; }}"
        )
        # Секционные заголовки
        section_qss = (
            f"QLabel#ExpertSection {{ color: {t['text_muted']}; font-size: 10px;"
            f" letter-spacing: 0.08em; padding: 4px 0 0; }}"
        )
        # Кнопки экспертной панели — компактные (26 px)
        btn_qss = (
            f"QPushButton#ExpertBtn {{ background: {t['expert_btn_bg']};"
            f" color: {t['expert_btn_fg']}; border: 1px solid {t['expert_btn_bdr']};"
            f" border-radius: 5px; padding: 5px 8px; font-size: 11px; min-height: 26px; }}"
            f" QPushButton#ExpertBtn:hover {{ background: {t['border']};"
            f" border-color: {t['border_input']}; }}"
            f" QPushButton#ExpertBtn:checked {{ background: {t['btn_primary_bg']};"
            f" color: white; border-color: {t['btn_primary_bg']}; }}"
            f" QPushButton#ExpertBtn:checked:hover {{ background: {t['btn_primary_hover']}; }}"
            f" QPushButton#ExpertBtn:disabled {{ background: {t['expert_btn_dis_bg']};"
            f" color: {t['expert_btn_dis_fg']}; border-color: {t['btn_border']}; }}"
        )
        # Кнопка удаления — danger
        delete_qss = (
            f"QPushButton#ExpertDeleteBtn {{ background: {t['btn_danger']}; color: white;"
            f" border: none; border-radius: 5px; padding: 6px 10px; font-size: 12px;"
            f" min-height: 28px; }}"
            f" QPushButton#ExpertDeleteBtn:hover {{ background: {t['btn_danger_hover']}; }}"
            f" QPushButton#ExpertDeleteBtn:disabled {{ background: {t['btn_bg']};"
            f" color: {t['text_off']}; border: 1px solid {t['btn_border']}; }}"
        )
        # Прогрессбар + подсказка
        progress_qss = (
            f"QProgressBar {{ border: none; background: {t['bg_input']};"
            f" border-radius: 2px; }}"
            f" QProgressBar::chunk {{ background: {t['btn_primary_bg']};"
            f" border-radius: 2px; }}"
        )
        hint_qss = (
            f"#ExpertHint {{ color: {t['text_dim']}; font-size: 11px;"
            f" font-style: italic; padding: 2px 0; }}"
        )

        self.setStyleSheet(section_qss + btn_qss + delete_qss + progress_qss + hint_qss)
        self._update_display()

    # ==================================================================
    # Публичный API (без изменений)
    # ==================================================================

    def set_instrument(self, ctrl: BaseInstrument) -> None:
        self._ctrl = ctrl

    def set_signal(self, sig: PEMINSignal, idx: int) -> None:
        self._signal     = sig
        self._signal_idx = idx
        self._update_display()

    def clear_signal(self) -> None:
        self._signal     = None
        self._signal_idx = -1
        self._update_display()

    def enable_remeasure(self, enabled: bool) -> None:
        has = self._signal is not None
        for btn in (self._btn_essh, self._btn_esh, self._btn_peak, self._btn_manual):
            btn.setEnabled(enabled and has)
        if not self._btn_zero_span.isChecked():
            self._btn_zero_span.setEnabled(enabled and has)

    def enable_expert_mode(self, active: bool) -> None:
        self._expert_mode = active
        self._btn_delete.setVisible(active)
        self._btn_delete.setEnabled(active and self._signal is not None)
        if not active:
            self._lbl_hint.setText("")

    def set_threshold(self, db: float) -> None:
        self._threshold_db = db
        self._update_display()

    def set_zero_span_active(self, active: bool) -> None:
        self._btn_zero_span.setChecked(active)
        self._btn_zero_span.setText(
            "■ Остановить мониторинг" if active else "▷ Zero Span + ♪ Аудио"
        )

    # ==================================================================
    # Обновление отображения
    # ==================================================================

    def _update_display(self) -> None:
        sig = self._signal
        has = sig is not None
        ctrl_ok = (
            self._ctrl is not None
            and getattr(self._ctrl, "is_connected", False)
        )
        t = self._theme

        if not has:
            self._lbl_freq.setText("—")
            self._lbl_caption.setText("выберите сигнал в Результатах")
            self._lbl_status.setText("")
            self._lbl_status.setStyleSheet("")
            self._lbl_sig_v.setText("—")
            self._lbl_sh_v.setText("—")
            self._lbl_d_v.setText("—")
        else:
            self._lbl_freq.setText(f"{sig.frequency_hz / 1e6:.4f} МГц")
            self._lbl_caption.setText("выбрано в Результатах")
            self._lbl_sig_v.setText(f"{sig.amplitude_on_db:.1f}")
            self._lbl_sh_v.setText(f"{sig.amplitude_off_db:.1f}")
            self._lbl_d_v.setText(f"{sig.amplitude_diff_db:+.1f}")

            # Статус-чип: цвет фона по status_color
            color_map = {
                "green":  (t["tbl_status_ok"],   "ПЭМИН"),
                "red":    (t["tbl_status_fail"],  "Брак"),
                "blue":   (t["tbl_status_ext"],   "Внешний"),
                "yellow": (t["tbl_status_warn"],  "Ожидание"),
            }
            color, label = color_map.get(
                getattr(sig, "status_color", "yellow"),
                (t["tbl_status_wait"], "Ожидание"),
            )
            self._lbl_status.setText(label)
            self._lbl_status.setStyleSheet(
                f"#ExpertStatusChip {{ background: {color}; color: white;"
                f" font-size: 10px; font-weight: 600; padding: 3px 10px;"
                f" border-radius: 4px; }}"
            )

        # Подсказка «Вероятнее всего» — только в экспертном режиме
        if has and self._expert_mode and self._threshold_db is not None:
            if sig.amplitude_diff_db >= self._threshold_db:
                self._lbl_hint.setText(
                    f"<span style='color:{t['tbl_status_ok']}'>Вероятнее всего: ПЭМИН</span>"
                )
            else:
                self._lbl_hint.setText(
                    f"<span style='color:{t['tbl_status_fail']}'>"
                    "Вероятнее всего: Брак (ниже порога)</span>"
                )
        else:
            self._lbl_hint.setText("")

        for btn in (self._btn_essh, self._btn_esh, self._btn_peak, self._btn_manual):
            btn.setEnabled(has and ctrl_ok)
        if not self._btn_zero_span.isChecked():
            self._btn_zero_span.setEnabled(has and ctrl_ok)
        if self._expert_mode:
            self._btn_delete.setEnabled(has)

    # ==================================================================
    # Переизмерение (логика без изменений)
    # ==================================================================

    def _start_remeasure(self, mode: str) -> None:
        if self._signal is None or self._ctrl is None:
            return
        if self._worker and self._worker.isRunning():
            return
        n = 5 if mode == "peak" else 3
        self._worker = _RemeasureWorker(self._ctrl, self._signal, mode, n)
        self._worker.done.connect(self._on_remeasure_done)
        self._worker.error.connect(self._on_remeasure_error)
        self._worker.finished.connect(lambda: self._progress.setVisible(False))
        self._progress.setVisible(True)
        for btn in (self._btn_essh, self._btn_esh, self._btn_peak, self._btn_manual):
            btn.setEnabled(False)
        self._worker.start()

    def _on_remeasure_done(self, freq_hz: float, amp_db: float) -> None:
        sig  = self._signal
        mode = self._worker._mode if self._worker else "signal"
        if mode == "signal":
            sig.amplitude_on_db   = amp_db
            sig.amplitude_diff_db = amp_db - sig.amplitude_off_db
        elif mode == "noise":
            sig.amplitude_off_db  = amp_db
            sig.amplitude_diff_db = sig.amplitude_on_db - amp_db
        elif mode == "peak":
            sig.frequency_hz      = freq_hz
            sig.amplitude_on_db   = amp_db
            sig.amplitude_diff_db = amp_db - sig.amplitude_off_db
        self._update_display()
        self.signal_modified.emit(self._signal_idx)
        for btn in (self._btn_essh, self._btn_esh, self._btn_peak, self._btn_manual):
            btn.setEnabled(True)

    def _on_remeasure_error(self, msg: str) -> None:
        QMessageBox.warning(self, "Ошибка переизмерения", msg)
        for btn in (self._btn_essh, self._btn_esh, self._btn_peak, self._btn_manual):
            btn.setEnabled(True)

    def _set_manual_amplitude(self) -> None:
        if self._signal is None:
            return
        val, ok = QInputDialog.getDouble(
            self, "Задать уровень сигнала",
            "Введите уровень сигнала в дБ:",
            self._signal.amplitude_on_db,
            -200.0, 100.0, 1,
        )
        if ok:
            self._signal.amplitude_on_db   = val
            self._signal.amplitude_diff_db = val - self._signal.amplitude_off_db
            self._update_display()
            self.signal_modified.emit(self._signal_idx)

    def _toggle_zero_span(self, checked: bool) -> None:
        if checked:
            if self._signal is None:
                self._btn_zero_span.setChecked(False)
                return
            self.set_zero_span_active(True)
            self.zero_span_started.emit(self._signal.frequency_hz)
        else:
            self.set_zero_span_active(False)
            self.zero_span_stopped.emit()
