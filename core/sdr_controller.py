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
            if self.sdr:
                self.close()
            self.sdr = RtlSdr(device_index=self.device_index)
            print("✅ SDR успешно подключен")
        except Exception as e:
            raise RuntimeError(f"Не удалось подключить SDR: {str(e)}. "
                               f"Проверьте, не занято ли устройство другой программой.")

    def close(self) -> None:
        if self.sdr:
            try:
                self.sdr.close()
            except:
                pass
            self.sdr = None

    def configure(self, cfg: PanoramaConfig) -> None:
        if not self.sdr:
            raise RuntimeError("SDR не подключен.")
        
        self._cfg = cfg
        center = (cfg.start_freq_hz + cfg.stop_freq_hz) / 2
        span = cfg.stop_freq_hz - cfg.start_freq_hz
        
        # RTL-SDR ограничение: 250 кГц – 2.8 МГц
        # Добавляем небольшой запас (5-10%), чтобы края диапазона не обрезались фильтрами
        sample_rate = np.clip(span * 1.1, 250e3, 2.8e6)
        
        self.sdr.sample_rate = int(sample_rate)
        self.sdr.center_freq = int(center)
        
        if cfg.use_agc:
            self.sdr.gain = 'AUTO'
        else:
            self.sdr.gain = cfg.sdr_gain_db

    def capture_spectrum(self) -> Spectrum:
        if not self.sdr or not self._cfg:
            raise RuntimeError("SDR не настроен")
            
        cfg = self._cfg

        # Очистка буфера USB (важно для RTL-SDR)
        try:
            self.sdr.read_bytes(1024 * 32) 
        except:
            pass
        
        # Ограничение буфера памяти (макс 1M сэмплов за раз, читаем циклом если надо)
        # Но для усреднения нам нужно total_samples
        samples_per_chunk = cfg.fft_size
        num_chunks = cfg.averaging_count
        
        # Инициализация аккумуляторов
        avg_sum_power = np.zeros(cfg.fft_size, dtype=np.float64)
        max_hold_power = np.full(cfg.fft_size, -np.inf, dtype=np.float64)
        
        # Предварительный расчет окна (Hann)
        # Окно снижает уровень боковых лепестков, что критично для метода троек
        window = np.hanning(samples_per_chunk)

        for _ in range(num_chunks):
            try:
                raw = self.sdr.read_samples(samples_per_chunk)
            except Exception as e:
                raise RuntimeError(f"Ошибка чтения сэмплов: {e}")

            if len(raw) < samples_per_chunk:
                break

            # Применение окна
            windowed_samples = np.array(raw) * window
            
            # БПФ
            fft_vals = np.fft.fftshift(np.fft.fft(windowed_samples))
            power = np.abs(fft_vals)**2
            
            # Накопление для Average
            avg_sum_power += power
            
            # Накопление для MaxHold
            np.maximum(max_hold_power, power, out=max_hold_power)

        # Выбор детектора
        if cfg.use_max_hold:
            power_sel = max_hold_power
        else:
            power_sel = avg_sum_power / num_chunks
            
        # Перевод в дБ
        # Добавляем малое число, чтобы избежать log(0)
        db_vals = 10 * np.log10(power_sel + 1e-12) + cfg.calibration_offset_db
        
        # Частотная ось
        freqs = np.fft.fftshift(np.fft.fftfreq(cfg.fft_size, d=1/self.sdr.sample_rate))
        freqs += self.sdr.center_freq
        
        # Фильтрация по диапазону (mask)
        mask = (freqs >= cfg.start_freq_hz) & (freqs <= cfg.stop_freq_hz)
        
        return Spectrum(
            frequencies_hz=freqs[mask], 
            amplitudes_db=db_vals[mask], 
            rbw_hz=self.sdr.sample_rate / cfg.fft_size, 
            timestamp=time.time()
        )