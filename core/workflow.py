import time
from typing import Callable, List
from .sdr_controller import SDRController
from .processor import PanoramaProcessor
from .models import Spectrum, PEMINSignal
from .config import PanoramaConfig
import numpy as np

class MeasurementWorkflow:
    def __init__(self, ctrl: SDRController, cfg: PanoramaConfig):
        self.ctrl = ctrl
        self.cfg = cfg
        self.proc = PanoramaProcessor(cfg)
        self.signals: List[PEMINSignal] = []
        
        self.on_status = lambda s: None
        self.on_progress = lambda p: None
        self.on_data = lambda a,b,c: None
        # Сигнал: (Заголовок этапа, Подробное описание процесса, ТекстКнопки)
        self.on_user_action_needed = lambda title, desc, btn: None 

    def run_discovery_phase_1(self):
        """Шаг 1: Измерение шума"""
        self.on_status("ЭТАП 1: ИЗМЕРЕНИЕ ФОНА")
        self.on_progress(10)
        try:
            # Небольшая задержка для стабилизации SDR
            time.sleep(0.5)
            off = self.ctrl.capture_spectrum()
            self._off_spectrum = off
            self.on_progress(35)
            
            self.on_user_action_needed(
                "ФОН ИЗМЕРЕН", 
                "Программа зафиксировала уровень индустриального шума.\n\n"
                "🔴 ВАШЕ ДЕЙСТВИЕ:\n"
                "1. Включите тестовый сигнал на исследуемом устройстве.\n"
                "2. Убедитесь, что антенна установлена корректно.\n"
                "3. Нажмите кнопку ниже для измерения сигнала.",
                "ИЗМЕРИТЬ СИГНАЛ (ТЕСТ ВКЛ)"
            )
        except Exception as e:
            self.on_status(f"ОШИБКА: {str(e)}")

    def run_discovery_phase_2(self):
        """Шаг 2: Измерение сигнала и поиск"""
        self.on_status("ЭТАП 2: ПОИСК СИГНАЛОВ ПЭМИН")
        self.on_progress(40)
        try:
            on = self.ctrl.capture_spectrum()
            self.on_progress(60)
            
            self.on_status("АНАЛИЗ СПЕКТРА...")
            diff = self.proc.subtract(on, self._off_spectrum)
            self.on_data(on, self._off_spectrum, diff)
            self.signals = self.proc.detect(diff, on)
            self.on_progress(80)
            
            count = len(self.signals)
            self.on_user_action_needed(
                f"ОБНАРУЖЕНО СИГНАЛОВ: {count}", 
                "Программа вычислила разность панорам и нашла пики, превышающие порог.\n\n"
                "🟡 ВАШЕ ДЕЙСТВИЕ:\n"
                "Убедитесь, что тестовый сигнал ВСЕ ЕЩЕ ВКЛЮЧЕН.\n"
                "Нажмите кнопку для запуска первой верификации (проверка стабильности).",
                "ЗАПУСТИТЬ ВЕРИФИКАЦИЮ 1"
            )
        except Exception as e:
            self.on_status(f"ОШИБКА: {str(e)}")

    def run_verification_1(self):
        """Шаг 3: Верификация 1"""
        self.on_status("ЭТАП 3: ВЕРИФИКАЦИЯ 1 (ON)")
        total = len(self.signals)
        if total == 0:
            self.on_user_action_needed("НЕТ СИГНАЛОВ", "Сигналы не найдены. Можно переходить к следующему этапу.", "ЗАПУСТИТЬ ВЕРИФИКАЦИЮ 2")
            return

        for i, sig in enumerate(self.signals):
            spec = self.ctrl.capture_spectrum()
            idx = np.argmin(np.abs(spec.frequencies_hz - sig.frequency_hz))
            sig.verified_1 = self.proc.verify_1(sig, spec.amplitudes_db[idx])
            sig.status_color = "red" if not sig.verified_1 else "yellow"
            self.on_progress(80 + int(((i + 1) / total) * 5))
        
        self.on_user_action_needed(
            "ВЕРИФИКАЦИЯ 1 ЗАВЕРШЕНА", 
            "Программа проверила стабильность сигналов при включенном тесте.\n\n"
            "🔵 ВАШЕ ДЕЙСТВИЕ:\n"
            "1. ВЫКЛЮЧИТЕ тестовый сигнал на устройстве.\n"
            "2. Нажмите кнопку для проверки на внешние помехи (Верификация 2).",
            "ЗАПУСТИТЬ ВЕРИФИКАЦИЮ 2 (ТЕСТ ВЫКЛ)"
        )

    def run_verification_2(self):
        """Шаг 4: Верификация 2"""
        self.on_status("ЭТАП 4: ВЕРИФИКАЦИЯ 2 (OFF)")
        total = len(self.signals)
        if total == 0:
            self.on_progress(100)
            self.on_user_action_needed("РАБОТА ЗАВЕРШЕНА", "Все этапы пройдены.", "СБРОС И НОВЫЙ ПОИСК")
            return

        for i, sig in enumerate(self.signals):
            spec = self.ctrl.capture_spectrum()
            idx = np.argmin(np.abs(spec.frequencies_hz - sig.frequency_hz))
            sig.verified_2 = self.proc.verify_2(sig, spec.amplitudes_db[idx])
            # Если верификация 2 не прошла (сигнал остался при выкл тесте) - это помеха (красный)
            # Если прошла (сигнал исчез) - это ПЭМИН (зеленый)
            sig.status_color = "green" if sig.verified_2 else "red" 
            self.on_progress(90 + int(((i + 1) / total) * 10))
        
        self.on_progress(100)
        self.on_user_action_needed(
            "РАБОТА ПОЛНОСТЬЮ ЗАВЕРШЕНА", 
            "Все измерения и верификации выполнены.\n"
            "Результаты отображены в таблице.\n"
            "Зеленые маркеры - подтвержденные ПЭМИН.\n"
            "Красные маркеры - отбракованные помехи.",
            "СБРОС И НОВЫЙ ПОИСК"
        )