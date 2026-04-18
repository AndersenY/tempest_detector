from dataclasses import dataclass

@dataclass
class PanoramaConfig:
    start_freq_hz: float = 80e6
    stop_freq_hz: float = 100e6
    fft_size: int = 32768           # <-- УМЕНЬШИЛИ с 65536 до 32768 для скорости
    averaging_count: int = 10       # Можно увеличить до 20-30 для гладкости шума
    use_max_hold: bool = True
    threshold_db: float = 6.0
    calibration_offset_db: float = 0.0
    sdr_gain_db: float = 30.0
    use_agc: bool = False
    combine_triplets: bool = True
    verification_ratio: float = 0.5