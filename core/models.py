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
    
    # Флаги верификации
    is_triplet_representative: bool = False
    verified_1: Optional[bool] = None # В1: Тест ВКЛ (стабильность)
    verified_2: Optional[bool] = None # В2: Тест ВЫКЛ (отсутствие в фоне)
    
    # Статус для GUI: "yellow" (найден), "red" (не В1), "green" (В1 ок, В2 ок), "blue" (не В1 и не В2)
    status_color: str = "yellow"
    
    # Индекс в массиве спектра для быстрой верификации
    spectrum_index: int = -1 