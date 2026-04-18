import numpy as np
import time
from pyrtlsdr import RtlSdr
from .models import SpectrumData, PanoramaConfig

class RtlSdrAnalyzer:
    """Адаптер для RTL-SDR с программным БПФ, усреднением и MaxHold"""
    
    def __init__(self, device_index: int = 0):
        self.sdr: RtlSdr | None = None
        self.device_index = device_index
        self.fft_size = 65536
        self.sample_rate = 2.4e6  # Макс. стабильная для RTL-SDR
        self.center_freq = 90e6
        self.gain = 30.0
        self.averaging_count = 1
        self.detector_mode = "PEAK"
        
        # Буферы для детекторов
        self._max_hold = None
        self._avg_accum = None
        self._sweep_counter = 0

    def connect(self, resource: str = "") -> None:
        self.sdr = RtlSdr(device_index=self.device_index)
        self.sdr.sample_rate = self.sample_rate
        self.sdr.center_freq = self.center_freq
        self.sdr.gain = self.gain if not getattr(self, 'use_agc', False) else 'AUTO'

    def configure(self, config: PanoramaConfig) -> None:
        self.fft_size = config.fft_size
        self.center_freq = config.center_freq_hz or (config.start_freq_hz + config.stop_freq_hz) / 2
        self.averaging_count = max(1, config.averaging_count)
        self.detector_mode = "MAXHOLD" if config.use_max_hold else "PEAK"
        
        self.sample_rate = min(2.8e6, max(250e3, (config.stop_freq_hz - config.start_freq_hz) * 1.1))
        self.sdr.sample_rate = self.sample_rate
        self.sdr.center_freq = self.center_freq
        
        if not config.use_agc:
            self.sdr.gain = config.manual_gain_db
            self.gain = config.manual_gain_db
            
        # Сброс буферов
        self._max_hold = None
        self._avg_accum = np.zeros(self.fft_size, dtype=np.float64)
        self._sweep_counter = 0

    def capture_spectrum(self) -> SpectrumData:
        if not self.sdr:
            raise RuntimeError("SDR not connected")
            
        total_samples = self.fft_size * self.averaging_count
        samples = self.sdr.read_samples(total_samples)
        
        # Обработка по чанкам
        for i in range(self.averaging_count):
            chunk = samples[i * self.fft_size : (i + 1) * self.fft_size]
            fft_vals = np.abs(np.fft.fftshift(np.fft.fft(chunk)))
            power_linear = fft_vals ** 2
            
            if self._max_hold is None:
                self._max_hold = power_linear.copy()
            else:
                np.maximum(self._max_hold, power_linear, out=self._max_hold)
                
            self._avg_accum += power_linear
            
        self._sweep_counter += 1
        
        # Выбор детектора
        if self.detector_mode == "MAXHOLD":
            power = self._max_hold
        else:
            power = self._avg_accum / self._sweep_counter
            
        # Преобразование в дБ (калибровочный коэффициент антенны/кабеля добавляется позже)
        power_db = 10 * np.log10(power + 1e-12)
        
        # Частотная ось
        freqs = np.fft.fftshift(np.fft.fftfreq(self.fft_size, d=1/self.sample_rate))
        freqs += self.center_freq
        
        # Фильтрация под диапазон (если задан)
        mask = (freqs >= self.center_freq - self.sample_rate/2) & \
               (freqs <= self.center_freq + self.sample_rate/2)
        freqs, power_db = freqs[mask], power_db[mask]
        
        return SpectrumData(
            frequencies=freqs,
            amplitudes=power_db,
            rbw_hz=self.sample_rate / self.fft_size,
            sweep_time_s=self.fft_size / self.sample_rate,
            is_max_hold=(self.detector_mode == "MAXHOLD"),
            timestamp=time.time()
        )