from dataclasses import dataclass


@dataclass
class PanoramaConfig:
    start_freq_hz: float = 80e6
    stop_freq_hz: float = 100e6
    fft_size: int = 32768
    # Рекомендуемое значение по РЭ п. 8.2: усреднение 10–15 раз подавляет шум
    # без использования MaxHold, который завышает уровень шума.
    averaging_count: int = 15
    # False = режим усреднения (рекомендован РЭ п. 8.2).
    # True = MaxHold — применяется только при низкочастотных тестовых сигналах
    # (п. 8.2, вариант 2), когда период тестового сигнала > времени измерения в точке.
    use_max_hold: bool = False
    threshold_db: float = 6.0
    calibration_offset_db: float = 0.0
    sdr_gain_db: float = 30.0
    use_agc: bool = False
    # Группировка смежных точек по алгоритму п. 6.2.2 РЭ
    combine_triplets: bool = True
    # Порог падения сигнала для В1: 50 % от исходного избытка над шумом
    verification_ratio: float = 0.5
    # Максимальный допустимый дрейф фона для В2 (дБ)
    v2_drift_limit_db: float = 6.0
    # Минимальное расстояние между кандидатами (Гц).
    # Если два кандидата ближе — остаётся только сильнейший.
    # 0 = фильтр отключён.
    min_separation_hz: float = 10_000.0