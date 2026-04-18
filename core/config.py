from dataclasses import dataclass

@dataclass
class PanoramaConfig:
    start_freq_hz: float = 80e6
    stop_freq_hz: float = 100e6
    fft_size: int = 32768           
    averaging_count: int = 15       # Увеличено до 15 для лучшего подавления шума (РЭ п. 8.2)
    use_max_hold: bool = False      # ИЗМЕНЕНО: False по умолчанию. MaxHold завышает шум.
    threshold_db: float = 6.0
    calibration_offset_db: float = 0.0
    sdr_gain_db: float = 30.0
    use_agc: bool = False
    combine_triplets: bool = True   # Группировка смежных точек (п. 6.2.2 РЭ)
    verification_ratio: float = 0.5 # Порог падения сигнала для В1 (50%)