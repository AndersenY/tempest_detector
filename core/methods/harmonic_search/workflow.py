import time
import threading
from typing import List
from ...sdr_controller import SDRController
from ...config import PanoramaConfig
from ...models import Spectrum, PEMINSignal
from ..base import AbstractDetectionMethod
from .processor import HarmonicProcessor


class HarmonicSearchWorkflow(AbstractDetectionMethod):
    """
    Метод поиска по гармоникам.

    Фазы:
      1. Измерение фона (ВЫКЛ) — опорный спектр для разности.
      2. Измерение сигнала (ВКЛ) + обнаружение кандидатов по порогу.
      3. Анализ гармоник: для каждого кандидата ищем n·f в diff-спектре.
      4. Классификация по количеству найденных гармоник.

    Верификация В1/В2 НЕ требуется — гармоническая структура является
    самостоятельным критерием принадлежности к ПЭМИН.
    """

    def __init__(self, ctrl: SDRController, cfg: PanoramaConfig):
        self.ctrl = ctrl
        self.cfg = cfg
        self.proc = HarmonicProcessor(cfg)
        self._signals: List[PEMINSignal] = []

        self._pause_event = threading.Event()
        self._stop_flag = False

        self.on_status = lambda s: None
        self.on_progress = lambda p: None
        self.on_data = lambda a, b, c: None
        self.on_user_action_needed = lambda title, desc, btn: None
        self.on_signal_updated = lambda: None

    @property
    def signals(self) -> List[PEMINSignal]:
        return self._signals

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
            self.on_progress(25)

            self.on_user_action_needed(
                "ФОН ИЗМЕРЕН",
                "1. Включите тестовый сигнал.\n2. Нажмите кнопку ниже.",
                "ИЗМЕРИТЬ СИГНАЛ (ТЕСТ ВКЛ)"
            )
            self._wait_for_user()

            # --- ЭТАП 2: ИЗМЕРЕНИЕ ON + ОБНАРУЖЕНИЕ КАНДИДАТОВ ---
            self.on_status("ЭТАП 2: ЗАХВАТ СПЕКТРА С ТЕСТОМ")
            self.on_progress(30)

            on_spec = self.ctrl.capture_spectrum()
            self.on_progress(50)

            self.on_status("ВЫЧИСЛЕНИЕ РАЗНОСТИ И ПОИСК КАНДИДАТОВ...")
            diff = self.proc.subtract(on_spec, off_spec)
            self.on_data(on_spec, off_spec, diff)

            candidates = self.proc.detect_candidates(diff, on_spec)
            self.on_progress(65)

            count = len(candidates)
            if count == 0:
                self.on_progress(100)
                self.on_user_action_needed(
                    "КАНДИДАТЫ НЕ НАЙДЕНЫ",
                    "Превышений порога не обнаружено.\n"
                    "Попробуйте уменьшить порог или изменить положение антенны.",
                    "СБРОС И НОВЫЙ ПОИСК"
                )
                return

            # --- ЭТАП 3: АНАЛИЗ ГАРМОНИК ---
            self.on_status(f"ЭТАП 3: АНАЛИЗ ГАРМОНИК ({count} кандидатов)")

            _last_update = time.monotonic()
            for i, sig in enumerate(candidates):
                if self._stop_flag:
                    raise InterruptedError("Stopped")

                # Анализируем гармоники для одного кандидата
                self.proc.analyze_harmonics([sig], diff, on_spec.frequencies_hz)

                now = time.monotonic()
                if now - _last_update >= 0.1 or (i + 1) == count:
                    self._signals = candidates[:i + 1]
                    self.on_signal_updated()
                    _last_update = now

                self.on_progress(65 + int(((i + 1) / count) * 30))

            self._signals = candidates

            # --- РЕЗУЛЬТАТ ---
            confirmed = sum(1 for s in self._signals if s.status_color == "green")
            uncertain = sum(1 for s in self._signals if s.status_color == "yellow")
            rejected = sum(1 for s in self._signals if s.status_color == "red")

            self.on_progress(100)
            self.on_user_action_needed(
                f"АНАЛИЗ ЗАВЕРШЁН: {count} кандидатов",
                f"Зелёные (ПЭМИН): {confirmed}\n"
                f"Жёлтые (неопределённо): {uncertain}\n"
                f"Красные (помехи): {rejected}\n\n"
                f"Критерий: гармоник ≥ {self.cfg.harmonic_min_count} → ПЭМИН",
                "СБРОС И НОВЫЙ ПОИСК"
            )

        except InterruptedError:
            self.on_status("ПРОЦЕСС ОСТАНОВЛЕН")
            self.on_progress(0)
        except Exception as e:
            self.on_status(f"ОШИБКА: {str(e)}")
            import traceback
            traceback.print_exc()
