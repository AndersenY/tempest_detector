import time
import numpy as np
from rtlsdr import RtlSdr
from .models import Spectrum
from .config import PanoramaConfig

class SDRController:
    def __init__(self, device_index: int = 0):
        self.sdr: RtlSdr | None = None
        self.device_index = device_index
        self._cfg = None

    def connect(self) -> None:
        try:
            # Если уже подключен, закрываем старое соединение
            if self.sdr:
                self.close()
            self.sdr = RtlSdr(device_index=self.device_index)
            print("✅ SDR успешно подключен")
        except Exception as e:
            raise RuntimeError(f"Не удалось подключить SDR: {str(e)}. "
                               f"Проверьте, не занято ли устройство другой программой (gqrx, rtl_test).")

    def close(self) -> None:
        if self.sdr:
            try:
                self.sdr.close()
            except:
                pass
            self.sdr = None

    def configure(self, cfg: PanoramaConfig) -> None:
        if not self.sdr:
            raise RuntimeError("SDR не подключен. Нажмите 'Подключить' сначала.")
        
        self._cfg = cfg
        center = (cfg.start_freq_hz + cfg.stop_freq_hz) / 2
        span = cfg.stop_freq_hz - cfg.start_freq_hz
        
        # RTL-SDR ограничение: 250 кГц – 2.8 МГц
        sample_rate = np.clip(span * 1.05, 250e3, 2.8e6)
        
        self.sdr.sample_rate = sample_rate
        self.sdr.center_freq = center
        
        if cfg.use_agc:
            self.sdr.gain = 'AUTO'
        else:
            self.sdr.gain = cfg.sdr_gain_db

    def capture_spectrum(self) -> Spectrum:
        if not self.sdr or not self._cfg:
            raise RuntimeError("SDR не настроен")
            
        cfg = self._cfg
        # Защита от слишком большого буфера памяти
        total_samples = min(cfg.fft_size * cfg.averaging_count, 2**20) 
        
        raw = self.sdr.read_samples(total_samples)
        
        max_hold = None
        avg_sum = np.zeros(cfg.fft_size, dtype=np.float64)
        
        # Обработка чанками
        for i in range(cfg.averaging_count):
            start_idx = i * cfg.fft_size
            end_idx = start_idx + cfg.fft_size
            if end_idx > len(raw): break
            
            chunk = raw[start_idx:end_idx]
            # Быстрое БПФ
            fft_vals = np.fft.fftshift(np.fft.fft(chunk))
            power = np.abs(fft_vals)**2
            
            if max_hold is None:
                max_hold = power.copy()
            else:
                np.maximum(max_hold, power, out=max_hold)
                
            avg_sum += power
            
        # Выбор детектора
        power_sel = max_hold if cfg.use_max_hold else (avg_sum / cfg.averaging_count)
        
        # Перевод в дБ
        db_vals = 10 * np.log10(power_sel + 1e-12) + cfg.calibration_offset_db
        
        # Частотная ось
        freqs = np.fft.fftshift(np.fft.fftfreq(cfg.fft_size, d=1/self.sdr.sample_rate))
        freqs += self.sdr.center_freq
        
        # Фильтрация по диапазону
        mask = (freqs >= cfg.start_freq_hz) & (freqs <= cfg.stop_freq_hz)
        
        return Spectrum(
            frequencies_hz=freqs[mask], 
            amplitudes_db=db_vals[mask], 
            rbw_hz=self.sdr.sample_rate / cfg.fft_size, 
            timestamp=time.time()
        )