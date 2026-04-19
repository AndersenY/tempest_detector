from dataclasses import dataclass, field
import numpy as np
from typing import List, Optional


@dataclass
class Spectrum:
    frequencies_hz: np.ndarray
    amplitudes_db: np.ndarray      # дБFS + калибровка
    rbw_hz: float
    timestamp: float = 0.0


@dataclass
class PEMINSignal:
    frequency_hz: float
    amplitude_diff_db: float       # Разница ON - OFF
    amplitude_on_db: float
    amplitude_off_db: float
    rbw_hz: float

    # Какой метод обнаружил сигнал
    detection_method: str = "panorama_diff"  # "panorama_diff" | "harmonic_search"

    # Флаги верификации (метод разности панорам)
    is_triplet_representative: bool = False
    verified_1: Optional[bool] = None   # В1: Тест ВКЛ (стабильность)
    verified_2: Optional[bool] = None   # В2: Тест ВЫКЛ (отсутствие в фоне)

    # Гармоники (метод поиска по гармоникам)
    harmonic_count: int = 0
    harmonic_frequencies_hz: List[float] = field(default_factory=list)
    harmonic_amplitudes_db: List[float] = field(default_factory=list)

    # Статус для GUI: "yellow" | "red" | "green" | "blue"
    status_color: str = "yellow"

    # Индекс в массиве спектра для быстрой верификации
    spectrum_index: int = -1