import numpy as np
from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QInputDialog, QMessageBox, QProgressBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from core.backends import BaseInstrument
from core.models import PEMINSignal
from core.signal_processor import find_peak_in_window
from core.audio_monitor import AudioMonitor


# ---------------------------------------------------------------------------
# Фоновый поток для переизмерений (не блокирует GUI)
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
# ExpertPanel — виджет экспертного анализа одного сигнала
# ---------------------------------------------------------------------------

class ExpertPanel(QGroupBox):
    """
    Панель экспертного режима (п. 3.1 ТЗ).

    Показывает детали выбранного ПЭМИН-сигнала и позволяет:
      • Переизмерить E(с+ш) / E(ш) — n захватов, берётся максимум.
      • Переизмерить частоту точнее (максимум из 5 точек в окне ±10·RBW).
      • Задать амплитуду вручную.
      • Включить / выключить аудиомонитор (тон ∝ уровню).

    Сигнал `signal_modified(idx)` испускается после каждого изменения,
    чтобы MainWindow мог перерисовать таблицу и маркеры.
    """

    signal_modified = pyqtSignal(int)   # индекс сигнала в списке

    _BTN = """
        QPushButton {
            background-color: #3a3a3a; color: #e0e0e0; border: 1px solid #555;
            border-radius: 3px; padding: 4px 8px; font-size: 12px;
        }
        QPushButton:hover   { background-color: #505050; }
        QPushButton:disabled { background-color: #2a2a2a; color: #666; }
    """
    _BTN_ACTIVE = """
        QPushButton {
            background-color: #1565C0; color: white; border: none;
            border-radius: 3px; padding: 4px 8px; font-size: 12px; font-weight: bold;
        }
        QPushButton:hover { background-color: #1976D2; }
    """

    def __init__(self, parent=None) -> None:
        super().__init__("Экспертный анализ", parent)
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold; border: 1px solid #555; border-radius: 5px;
                margin-top: 10px; padding-top: 8px; color: #e0e0e0;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLabel { color: #ccc; font-size: 12px; }
        """)

        self._signal: PEMINSignal | None = None
        self._signal_idx: int = -1
        self._ctrl: BaseInstrument | None = None
        self._worker: _RemeasureWorker | None = None
        self._audio = AudioMonitor()

        self._init_ui()
        self._update_display()

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    def set_instrument(self, ctrl: BaseInstrument) -> None:
        self._ctrl = ctrl

    def set_signal(self, sig: PEMINSignal, idx: int) -> None:
        self._signal     = sig
        self._signal_idx = idx
        self._update_display()
        if self._audio.active:
            self._audio.set_amplitude(sig.amplitude_on_db)

    def clear_signal(self) -> None:
        self._signal     = None
        self._signal_idx = -1
        self._update_display()

    def enable_remeasure(self, enabled: bool) -> None:
        """Разрешить/запретить кнопки переизмерения (нельзя во время workflow)."""
        for btn in (self._btn_essh, self._btn_esh, self._btn_peak, self._btn_manual):
            btn.setEnabled(enabled and self._signal is not None)

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 8)

        # ── Информация о сигнале ──────────────────────────────────────
        self._lbl_freq   = QLabel("—")
        self._lbl_levels = QLabel("—")
        self._lbl_status = QLabel("—")
        for lbl in (self._lbl_freq, self._lbl_levels, self._lbl_status):
            lbl.setWordWrap(True)
        root.addWidget(self._lbl_freq)
        root.addWidget(self._lbl_levels)
        root.addWidget(self._lbl_status)

        # ── Прогресс переизмерения ────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet("""
            QProgressBar { border: none; background: #333; border-radius: 3px; }
            QProgressBar::chunk { background: #2196F3; border-radius: 3px; }
        """)
        root.addWidget(self._progress)

        # ── Кнопки переизмерения ──────────────────────────────────────
        row1 = QHBoxLayout()
        self._btn_essh = QPushButton("Переизм. E(с+ш)")
        self._btn_esh  = QPushButton("Переизм. E(ш)")
        self._btn_essh.setStyleSheet(self._BTN)
        self._btn_esh.setStyleSheet(self._BTN)
        self._btn_essh.setToolTip("Захватить N спектров с включённым тестом, взять максимум")
        self._btn_esh.setToolTip("Захватить N спектров без теста, взять максимум")
        self._btn_essh.clicked.connect(lambda: self._start_remeasure("signal"))
        self._btn_esh.clicked.connect(lambda: self._start_remeasure("noise"))
        row1.addWidget(self._btn_essh)
        row1.addWidget(self._btn_esh)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        self._btn_peak   = QPushButton("Уточнить частоту (×5)")
        self._btn_manual = QPushButton("Задать вручную…")
        self._btn_peak.setStyleSheet(self._BTN)
        self._btn_manual.setStyleSheet(self._BTN)
        self._btn_peak.setToolTip("Найти точный максимум из 5 захватов в окне ±10·RBW")
        self._btn_manual.setToolTip("Вручную задать амплитуду E(с+ш)")
        self._btn_peak.clicked.connect(lambda: self._start_remeasure("peak"))
        self._btn_manual.clicked.connect(self._set_manual_amplitude)
        row2.addWidget(self._btn_peak)
        row2.addWidget(self._btn_manual)
        root.addLayout(row2)

        # ── Аудиомонитор ─────────────────────────────────────────────
        audio_row = QHBoxLayout()
        self._btn_audio = QPushButton("♪ Аудио ВЫКЛ")
        self._btn_audio.setCheckable(True)
        self._btn_audio.setStyleSheet(self._BTN)
        if not self._audio.available:
            self._btn_audio.setEnabled(False)
            self._btn_audio.setToolTip("Установите sounddevice: pip install sounddevice")
        else:
            self._btn_audio.clicked.connect(self._toggle_audio)
        self._lbl_audio_db = QLabel("")
        self._lbl_audio_db.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        audio_row.addWidget(self._btn_audio)
        audio_row.addWidget(self._lbl_audio_db)
        root.addLayout(audio_row)

    # ------------------------------------------------------------------
    # Обновление отображения
    # ------------------------------------------------------------------

    def _update_display(self) -> None:
        sig = self._signal
        has = sig is not None
        ctrl_ok = self._ctrl is not None and self._ctrl.is_connected

        if not has:
            self._lbl_freq.setText("<span style='color:#777'>Сигнал не выбран</span>")
            self._lbl_levels.setText("")
            self._lbl_status.setText("")
        else:
            self._lbl_freq.setText(
                f"<b>{sig.frequency_hz / 1e6:.4f} МГц</b>"
                f"  Δ <b>{sig.amplitude_diff_db:+.1f} дБ</b>"
            )
            self._lbl_levels.setText(
                f"E(с+ш) = <b>{sig.amplitude_on_db:.1f} дБ</b>"
                f"  &nbsp;  E(ш) = {sig.amplitude_off_db:.1f} дБ"
            )
            colors = {"green": "#66BB6A", "red": "#EF5350", "blue": "#42A5F5",
                      "yellow": "#FFCA28"}
            labels = {"green": "✅ ПЭМИН", "red": "❌ Брак (В1)",
                      "blue": "〇 Внешний", "yellow": "⏳ Ожидание"}
            c = sig.status_color
            color_str = colors.get(c, "#aaa")
            label_str = labels.get(c, c)
            self._lbl_status.setText(
                f"<span style='color:{color_str}'>{label_str}</span>"
            )
            if self._audio.active:
                self._audio.set_amplitude(sig.amplitude_on_db)
                self._lbl_audio_db.setText(f"{sig.amplitude_on_db:.1f} дБ")

        for btn in (self._btn_essh, self._btn_esh, self._btn_peak, self._btn_manual):
            btn.setEnabled(has and ctrl_ok)

    # ------------------------------------------------------------------
    # Переизмерение
    # ------------------------------------------------------------------

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

        self._worker._mode = mode
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
            self, "Задать амплитуду E(с+ш)",
            "Введите значение E(с+ш) в дБ:",
            self._signal.amplitude_on_db,
            -200.0, 100.0, 1,
        )
        if ok:
            self._signal.amplitude_on_db   = val
            self._signal.amplitude_diff_db = val - self._signal.amplitude_off_db
            self._update_display()
            self.signal_modified.emit(self._signal_idx)

    # ------------------------------------------------------------------
    # Аудиомонитор
    # ------------------------------------------------------------------

    def _toggle_audio(self, checked: bool) -> None:
        if checked:
            self._audio.start()
            self._btn_audio.setText("♪ Аудио ВКЛ")
            self._btn_audio.setStyleSheet(self._BTN_ACTIVE)
            if self._signal:
                self._audio.set_amplitude(self._signal.amplitude_on_db)
                self._lbl_audio_db.setText(f"{self._signal.amplitude_on_db:.1f} дБ")
        else:
            self._audio.stop()
            self._btn_audio.setText("♪ Аудио ВЫКЛ")
            self._btn_audio.setStyleSheet(self._BTN)
            self._lbl_audio_db.setText("")

    def closeEvent(self, event) -> None:
        self._audio.stop()
        super().closeEvent(event)
