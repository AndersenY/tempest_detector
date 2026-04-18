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
        
        # Синхронизация
        self._pause_event = threading.Event()
        self._stop_flag = False
        
        # Callbacks
        self.on_status = lambda s: None
        self.on_progress = lambda p: None
        self.on_data = lambda a,b,c: None
        self.on_user_action_needed = lambda title, desc, btn: None 

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
            
            # Отправляем данные для отрисовки
            self.on_data(on_spec, self._off_spectrum, diff)
            
            # Детектирование
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
                # ОПТИМИЗАЦИЯ: Снимаем ОДНУ панораму для всех сигналов сразу
                verify_on_spec = self.ctrl.capture_spectrum()
                
                for i, sig in enumerate(self.signals):
                    if self._stop_flag: raise InterruptedError("Stopped")
                    
                    # Берем значение из уже снятой панорамы по сохраненному индексу
                    # Индекс мог сместиться, если диапазоны разные, но при неизменной конф. он точен
                    if 0 <= sig.spectrum_index < len(verify_on_spec.amplitudes_db):
                        current_amp = verify_on_spec.amplitudes_db[sig.spectrum_index]
                    else:
                        # Fallback: поиск ближайшей частоты (медленнее)
                        idx = np.argmin(np.abs(verify_on_spec.frequencies_hz - sig.frequency_hz))
                        current_amp = verify_on_spec.amplitudes_db[idx]
                        sig.spectrum_index = idx # Обновляем индекс

                    passed = self.proc.verify_1(sig, current_amp)
                    sig.verified_1 = passed
                    
                    # Цветовая кодировка (предварительная)
                    if not passed:
                        sig.status_color = "red" # Не прошел В1
                    else:
                        sig.status_color = "yellow" # Пока желтый, ждем В2

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
                # ОПТИМИЗАЦИЯ: Снимаем ОДНУ панораму фона
                verify_off_spec = self.ctrl.capture_spectrum()
                
                for i, sig in enumerate(self.signals):
                    if self._stop_flag: raise InterruptedError("Stopped")

                    if 0 <= sig.spectrum_index < len(verify_off_spec.amplitudes_db):
                        current_noise = verify_off_spec.amplitudes_db[sig.spectrum_index]
                    else:
                        idx = np.argmin(np.abs(verify_off_spec.frequencies_hz - sig.frequency_hz))
                        current_noise = verify_off_spec.amplitudes_db[idx]

                    passed = self.proc.verify_2(sig, current_noise)
                    sig.verified_2 = passed
                    
                    # ФИНАЛЬНАЯ ЦВЕТОВАЯ ЛОГИКА (п. 7.4 РЭ)
                    if not sig.verified_1:
                        # Если не прошел В1, он уже красный. 
                        # Если не прошел и В2 тоже -> Синий (по рекомендации РЭ для двойного брака)
                        if not passed:
                            sig.status_color = "blue"
                        else:
                            sig.status_color = "red"
                    else:
                        # Если прошел В1
                        if passed:
                            sig.status_color = "green" # Все ОК
                        else:
                            sig.status_color = "red" # Прошел В1, но фон загрязнен (В2 fail)
                            # Примечание: В некоторых интерпретациях В2 fail = зеленый маркер "помеха фона", 
                            # но для итогового списка ПЭМИН это брак. Оставим красным для внимания.

                    progress_val = 85 + int(((i + 1) / total) * 15)
                    self.on_progress(progress_val)
            
            self.on_progress(100)
            self.on_user_action_needed(
                "РАБОТА ЗАВЕРШЕНА", 
                "Зеленые - ПЭМИН. Красные/Синие - Помехи.",
                "СБРОС И НОВЫЙ ПОИСК"
            )

        except InterruptedError:
            self.on_status("ПРОЦЕСС ОСТАНОВЛЕН")
            self.on_progress(0)
        except Exception as e:
            self.on_status(f"ОШИБКА: {str(e)}")
            import traceback
            traceback.print_exc()