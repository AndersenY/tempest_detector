import time
import threading
import numpy as np
from typing import Callable, List
from ...backends import BaseInstrument
from ...config import PanoramaConfig
from ...models import Spectrum, PEMINSignal
from ..base import AbstractDetectionMethod
from .processor import PanoramaProcessor


class PanoramaDiffWorkflow(AbstractDetectionMethod):
    """
    Метод разности панорам (ON − OFF).
    Фазы: фон → сигнал → В1 (стабильность ВКЛ) → В2 (чистота ВЫКЛ).

    preset_candidates_hz — список частот (Гц), помеченных пользователем в live-режиме.
    Они добавляются в список кандидатов после автоматического detect() и проходят
    ту же верификацию В1/В2 что и автоматически найденные сигналы.
    """

    def __init__(self, ctrl: BaseInstrument, cfg: PanoramaConfig,
                 preset_candidates_hz: List[float] | None = None):
        self.ctrl = ctrl
        self.cfg = cfg
        self.proc = PanoramaProcessor(cfg)
        self._signals: List[PEMINSignal] = []
        self._preset_candidates_hz: List[float] = list(preset_candidates_hz or [])

        self._pause_event = threading.Event()
        self._stop_flag = False

        self.on_status = lambda s: None
        self.on_progress = lambda p: None
        self.on_data = lambda a, b, c: None
        self.on_user_action_needed = lambda title, desc, btn: None
        self.on_signal_updated = lambda: None
        self.on_off_spectrum = lambda spec: None   # вызывается сразу после захвата фона

    @property
    def signals(self) -> List[PEMINSignal]:
        return self._signals

    def _wait_for_user(self):
        self._pause_event.clear()
        # Poll with a short timeout so _stop_flag is checked promptly
        # even if stop() is called between event.clear() and event.wait().
        while not self._pause_event.wait(timeout=0.2):
            if self._stop_flag:
                raise InterruptedError("Process stopped by user")
        if self._stop_flag:
            raise InterruptedError("Process stopped by user")

    def resume(self):
        self._pause_event.set()

    def stop(self):
        self._stop_flag = True
        self._pause_event.set()

    def run_full_cycle(self):
        try:
            self._stop_flag = False

            # --- ЭТАП 1: ФОН (OFF) ---
            self.on_status("ЭТАП 1: ИЗМЕРЕНИЕ ФОНА (ВЫКЛ)")
            self.on_progress(5)
            time.sleep(0.5)

            off_spec = self.ctrl.capture_spectrum()
            self._off_spectrum = off_spec
            self.on_off_spectrum(off_spec)   # сразу показываем фон на графике
            self.on_progress(25)

            self.on_user_action_needed(
                "ФОН ИЗМЕРЕН",
                "1. Включите тестовый сигнал.\n2. Нажмите кнопку ниже.",
                "ИЗМЕРИТЬ СИГНАЛ (ТЕСТ ВКЛ)"
            )
            self._wait_for_user()

            # --- ЭТАП 2: СИГНАЛ (ON) И ПОИСК ---
            self.on_status("ЭТАП 2: ПОИСК СИГНАЛОВ ПЭМИН")
            self.on_progress(30)

            on_spec = self.ctrl.capture_spectrum()
            self.on_progress(50)

            self.on_status("АНАЛИЗ СПЕКТРА...")
            diff = self.proc.subtract(on_spec, off_spec)
            self.on_data(on_spec, off_spec, diff)

            self._signals = self.proc.detect(diff, on_spec)
            self._merge_bookmark_candidates(on_spec, off_spec)
            self.on_progress(70)

            count = len(self._signals)
            msg = f"ОБНАРУЖЕНО СИГНАЛОВ: {count}"
            if count == 0:
                msg += "\nПопробуйте уменьшить порог или изменить положение антенны."

            if self.cfg.skip_verification:
                self.on_progress(100)
                self.on_user_action_needed(
                    msg,
                    "Быстрое сканирование завершено. Верификация пропущена.",
                    "СБРОС И НОВЫЙ ПОИСК"
                )
                return

            self.on_user_action_needed(
                msg,
                "Убедитесь, что тест ВСЕ ЕЩЕ ВКЛЮЧЕН.\nНажмите для Верификации 1.",
                "ЗАПУСТИТЬ ВЕРИФИКАЦИЮ 1"
            )
            self._wait_for_user()

            # --- ЭТАП 3: ВЕРИФИКАЦИЯ 1 (ON Stability) ---
            self.on_status("ЭТАП 3: ВЕРИФИКАЦИЯ 1 (Стабильность ВКЛ)")
            total = len(self._signals)

            if total > 0:
                verify_on_spec = self.ctrl.capture_spectrum()
                _last_update = time.monotonic()
                for i, sig in enumerate(self._signals):
                    if self._stop_flag:
                        raise InterruptedError("Stopped")

                    if 0 <= sig.spectrum_index < len(verify_on_spec.amplitudes_db):
                        current_amp = verify_on_spec.amplitudes_db[sig.spectrum_index]
                    else:
                        idx = np.argmin(np.abs(verify_on_spec.frequencies_hz - sig.frequency_hz))
                        current_amp = verify_on_spec.amplitudes_db[idx]
                        sig.spectrum_index = idx

                    passed = self.proc.verify_1(sig, current_amp)
                    sig.verified_1 = passed
                    sig.status_color = "yellow" if passed else "red"

                    now = time.monotonic()
                    if now - _last_update >= 0.1 or (i + 1) == total:
                        self.on_signal_updated()
                        _last_update = now

                    self.on_progress(70 + int(((i + 1) / total) * 15))

            self.on_user_action_needed(
                "ВЕРИФИКАЦИЯ 1 ЗАВЕРШЕНА",
                "1. ВЫКЛЮЧИТЕ тестовый сигнал.\n2. Нажмите кнопку для Верификации 2.",
                "ЗАПУСТИТЬ ВЕРИФИКАЦИЮ 2 (ТЕСТ ВЫКЛ)"
            )
            self._wait_for_user()

            # --- ЭТАП 4: ВЕРИФИКАЦИЯ 2 (OFF Cleanliness) ---
            self.on_status("ЭТАП 4: ВЕРИФИКАЦИЯ 2 (Чистота ВЫКЛ)")
            if total > 0:
                verify_off_spec = self.ctrl.capture_spectrum()
                _last_update = time.monotonic()
                for i, sig in enumerate(self._signals):
                    if self._stop_flag:
                        raise InterruptedError("Stopped")

                    if 0 <= sig.spectrum_index < len(verify_off_spec.amplitudes_db):
                        current_noise = verify_off_spec.amplitudes_db[sig.spectrum_index]
                    else:
                        idx = np.argmin(np.abs(verify_off_spec.frequencies_hz - sig.frequency_hz))
                        current_noise = verify_off_spec.amplitudes_db[idx]

                    passed = self.proc.verify_2(sig, current_noise)
                    sig.verified_2 = passed

                    if sig.verified_1 and passed:
                        sig.status_color = "green"
                    elif sig.verified_1 and not passed:
                        sig.status_color = "blue"
                    else:
                        sig.status_color = "blue" if passed else "red"

                    now = time.monotonic()
                    if now - _last_update >= 0.1 or (i + 1) == total:
                        self.on_signal_updated()
                        _last_update = now

                    self.on_progress(85 + int(((i + 1) / total) * 15))

            self.on_progress(100)
            self.on_user_action_needed(
                "РАБОТА ЗАВЕРШЕНА",
                "Зелёные — ПЭМИН.\nКрасные — нестабильные помехи.\nСиние — внешние сигналы / двойной брак.",
                "СБРОС И НОВЫЙ ПОИСК"
            )

        except InterruptedError:
            self.on_status("ПРОЦЕСС ОСТАНОВЛЕН")
            self.on_progress(0)
        except Exception as e:
            self.on_status(f"ОШИБКА: {str(e)}")
            import traceback
            traceback.print_exc()

    def _merge_bookmark_candidates(self, on_spec: Spectrum, off_spec: Spectrum) -> None:
        """Добавляет помеченные частоты как кандидатов, если auto-detect их не нашёл."""
        if not self._preset_candidates_hz:
            return
        rbw = on_spec.rbw_hz
        tol = max(rbw * 3, 10_000)   # допуск: 3 RBW или минимум 10 кГц
        for freq_hz in self._preset_candidates_hz:
            matched = next(
                (s for s in self._signals if abs(s.frequency_hz - freq_hz) < tol), None
            )
            if matched is not None:
                matched.detection_method = "bookmark"  # сохраняем метку пользователя
                continue
            idx = int(np.argmin(np.abs(on_spec.frequencies_hz - freq_hz)))
            amp_on  = float(on_spec.amplitudes_db[idx])
            amp_off = float(off_spec.amplitudes_db[idx])
            sig = PEMINSignal(
                frequency_hz=float(on_spec.frequencies_hz[idx]),
                amplitude_diff_db=amp_on - amp_off,
                amplitude_on_db=amp_on,
                amplitude_off_db=amp_off,
                rbw_hz=rbw,
                detection_method="bookmark",
                spectrum_index=idx,
            )
            self._signals.append(sig)
