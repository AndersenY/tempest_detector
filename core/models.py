from dataclasses import dataclass
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
    is_triplet_representative: bool = False
    verified_1: Optional[bool] = None
    verified_2: Optional[bool] = None
    status_color: str = "yellow"