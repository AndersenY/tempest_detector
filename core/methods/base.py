from abc import ABC, abstractmethod
from typing import Callable, List
from ..models import Spectrum, PEMINSignal
import numpy as np


class AbstractDetectionMethod(ABC):
    """Базовый интерфейс для всех методов обнаружения ПЭМИН."""

    # Колбэки — устанавливаются снаружи (Worker-ом или тестами)
    on_status: Callable[[str], None]
    on_progress: Callable[[int], None]
    on_data: Callable[[Spectrum, Spectrum, np.ndarray], None]
    on_user_action_needed: Callable[[str, str, str], None]
    on_signal_updated: Callable[[], None]

    @property
    @abstractmethod
    def signals(self) -> List[PEMINSignal]:
        """Список сигналов, найденных последним запуском."""

    @abstractmethod
    def run_full_cycle(self) -> None:
        """Запустить полный цикл измерения. Блокирует поток."""

    @abstractmethod
    def resume(self) -> None:
        """Продолжить после паузы (ответ на on_user_action_needed)."""

    @abstractmethod
    def stop(self) -> None:
        """Прервать цикл измерения."""
