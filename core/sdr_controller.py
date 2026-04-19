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

    # Максимально безопасная полоса RTL-SDR (при большей — нестабильность)
    _SAFE_SR   = 2_400_000   # sample rate на один шаг
    _USABLE_BW = 2_000_000   # полезная полоса шага (отбрасываем ±10% краёв)

    def configure(self, cfg: PanoramaConfig) -> None:
        if not self.sdr:
            raise RuntimeError("SDR не подключен.")

        self._cfg = cfg
        span = cfg.stop_freq_hz - cfg.start_freq_hz

        if span <= self._USABLE_BW:
            # Один захват: sample_rate покрывает весь диапазон
            sr = int(np.clip(span * 1.15, 250_000, self._SAFE_SR))
            self.sdr.center_freq = int((cfg.start_freq_hz + cfg.stop_freq_hz) / 2)
        else:
            # Sweep-режим: фиксированный sample_rate, center будет меняться при захвате
            sr = self._SAFE_SR
            self.sdr.center_freq = int(cfg.start_freq_hz + sr / 2)

        self.sdr.sample_rate = sr

        if cfg.use_agc:
            self.sdr.gain = 'AUTO'
        else:
            self.sdr.gain = cfg.sdr_gain_db

    # ------------------------------------------------------------------

    def capture_spectrum(self) -> Spectrum:
        if not self.sdr or not self._cfg:
            raise RuntimeError("SDR не настроен")

        cfg = self._cfg
        span = cfg.stop_freq_hz - cfg.start_freq_hz

        if span <= self._USABLE_BW:
            return self._capture_single(cfg.start_freq_hz, cfg.stop_freq_hz, cfg)
        else:
            return self._capture_sweep(cfg)

    # ------------------------------------------------------------------

    def _capture_single(self, start_hz: float, stop_hz: float,
                        cfg: PanoramaConfig) -> Spectrum:
        """Один захват с текущим center_freq."""
        try:
            self.sdr.read_bytes(1024 * 16)
        except Exception:
            pass

        window = np.hanning(cfg.fft_size)
        avg_power = np.zeros(cfg.fft_size, dtype=np.float64)
        max_power = np.full(cfg.fft_size, -np.inf, dtype=np.float64)

        for _ in range(cfg.averaging_count):
            time.sleep(0.01)
            try:
                raw = self.sdr.read_samples(cfg.fft_size)
            except Exception as e:
                raise RuntimeError(f"Ошибка чтения сэмплов: {e}")
            if len(raw) < cfg.fft_size:
                break
            fft_vals = np.fft.fftshift(np.fft.fft(np.array(raw) * window))
            power = np.abs(fft_vals) ** 2
            avg_power += power
            np.maximum(max_power, power, out=max_power)

        power_sel = max_power if cfg.use_max_hold else avg_power / cfg.averaging_count
        db_vals = 10 * np.log10(power_sel + 1e-12) + cfg.calibration_offset_db

        sr = self.sdr.sample_rate
        freqs = np.fft.fftshift(np.fft.fftfreq(cfg.fft_size, d=1.0 / sr))
        freqs += self.sdr.center_freq

        mask = (freqs >= start_hz) & (freqs <= stop_hz)
        return Spectrum(
            frequencies_hz=freqs[mask],
            amplitudes_db=db_vals[mask],
            rbw_hz=sr / cfg.fft_size,
            timestamp=time.time(),
        )

    def _capture_sweep(self, cfg: PanoramaConfig) -> Spectrum:
        """
        Пошаговая развёртка для диапазонов шире _USABLE_BW.
        Каждый шаг — один захват _capture_single, шаги склеиваются.
        """
        sr = self._SAFE_SR
        step = self._USABLE_BW   # шаг между центрами (без перекрытия краёв)

        centers = []
        c = cfg.start_freq_hz + sr / 2
        while c - sr / 2 < cfg.stop_freq_hz:
            centers.append(c)
            c += step

        all_freqs_list = []
        all_db_list = []

        for center in centers:
            self.sdr.center_freq = int(center)
            time.sleep(0.05)   # ждём стабилизации PLL

            # Полезная полоса этого шага (отбрасываем ±10% краёв)
            step_start = max(center - step / 2, cfg.start_freq_hz)
            step_stop  = min(center + step / 2, cfg.stop_freq_hz)

            chunk = self._capture_single(step_start, step_stop, cfg)
            all_freqs_list.append(chunk.frequencies_hz)
            all_db_list.append(chunk.amplitudes_db)

        freqs_all = np.concatenate(all_freqs_list)
        db_all    = np.concatenate(all_db_list)

        order = np.argsort(freqs_all)
        return Spectrum(
            frequencies_hz=freqs_all[order],
            amplitudes_db=db_all[order],
            rbw_hz=sr / cfg.fft_size,
            timestamp=time.time(),
        )