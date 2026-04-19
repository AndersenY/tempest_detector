import time
import threading
import numpy as np
from typing import Callable, List
from .sdr_controller import SDRController
from .processor import PanoramaProcessor
from .models import Spectrum, PEMINSignal
from .config import PanoramaConfig


class MeasurementWorkflow:
    def __init__(self, ctrl: SDRController, cfg: PanoramaConfig):
        self.ctrl = ctrl
        self.cfg = cfg
        self.proc = PanoramaProcessor(cfg)
        self.signals: List[PEMINSignal] = []

        self._pause_event = threading.Event()
        self._stop_flag = False

        self.on_status = lambda s: None
        self.on_progress = lambda p: None
        self.on_data = lambda a, b, c: None
        self.on_user_action_needed = lambda title, desc, btn: None
        self.on_signal_updated = lambda: None   # вызывается после смены статуса каждого сигнала

    def _wait_for_user(self):
        self._pause_event.clear()
        while not self._pause_event.is_set() and not self._stop_flag:
            time.sleep(0.1)
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
            diff = self.proc.subtract(on_spec, self._off_spectrum)
            self.on_data(on_spec, self._off_spectrum, diff)

            self.signals = self.proc.detect(diff, on_spec)
            self.on_progress(70)

            count = len(self.signals)
            msg = f"ОБНАРУЖЕНО СИГНАЛОВ: {count}"
            if count == 0:
                msg += "\nПопробуйте уменьшить порог или изменить положение антенны."

            self.on_user_action_needed(
                msg,
                "Убедитесь, что тест ВСЕ ЕЩЕ ВКЛЮЧЕН.\nНажмите для Верификации 1.",
                "ЗАПУСТИТЬ ВЕРИФИКАЦИЮ 1"
            )
            self._wait_for_user()

            # --- ЭТАП 3: ВЕРИФИКАЦИЯ 1 (ON Stability) ---
            self.on_status("ЭТАП 3: ВЕРИФИКАЦИЯ 1 (Стабильность ВКЛ)")
            total = len(self.signals)

            if total > 0:
                verify_on_spec = self.ctrl.capture_spectrum()

                _last_update = time.monotonic()
                for i, sig in enumerate(self.signals):
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

                    if passed:
                        sig.status_color = "yellow"  # В1 OK, ждём В2
                    else:
                        sig.status_color = "red"     # В1 провален — уже брак

                    # Обновляем GUI не чаще 10 раз/с, чтобы не заваливать очередь событий
                    now = time.monotonic()
                    if now - _last_update >= 0.1 or (i + 1) == total:
                        self.on_signal_updated()
                        _last_update = now

                    progress_val = 70 + int(((i + 1) / total) * 15)
                    self.on_progress(progress_val)

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
                for i, sig in enumerate(self.signals):
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
                    elif not sig.verified_1 and passed:
                        sig.status_color = "red"
                    else:
                        sig.status_color = "blue"

                    now = time.monotonic()
                    if now - _last_update >= 0.1 or (i + 1) == total:
                        self.on_signal_updated()
                        _last_update = now

                    progress_val = 85 + int(((i + 1) / total) * 15)
                    self.on_progress(progress_val)

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