import time
import numpy as np
from rtlsdr import RtlSdr
from .base import BaseInstrument
from ..config import PanoramaConfig
from ..models import Spectrum


class RtlSdrBackend(BaseInstrument):
    """RTL-SDR бэкенд — прямой преемник SDRController."""

    _SAFE_SR   = 2_400_000
    _USABLE_BW = 2_000_000

    def __init__(self, device_index: int = 0):
        self._sdr: RtlSdr | None = None
        self._device_index = device_index
        self._cfg: PanoramaConfig | None = None

    @property
    def name(self) -> str:
        return f"RTL-SDR (устройство {self._device_index})"

    @property
    def is_connected(self) -> bool:
        return self._sdr is not None

    def connect(self) -> None:
        try:
            if self._sdr:
                self.close()
            self._sdr = RtlSdr(device_index=self._device_index)
            print("✅ RTL-SDR подключён")
        except Exception as e:
            raise RuntimeError(
                f"Не удалось подключить RTL-SDR: {e}. "
                "Проверьте, не занято ли устройство другой программой."
            )

    def close(self) -> None:
        if self._sdr:
            try:
                self._sdr.close()
            except Exception:
                pass
            self._sdr = None

    # RTL-SDR нестабилен при sample rate в диапазоне 300–900 кГц — segfault/PLL fail.
    # При попадании в эту зону принудительно используем ближайшее безопасное значение.
    _SR_DEAD_LOW  = 300_001
    _SR_DEAD_HIGH = 900_000
    _SR_SNAP      = 1_024_000   # ближайший надёжный rate выше мёртвой зоны

    def _safe_sr(self, sr: int) -> int:
        if self._SR_DEAD_LOW <= sr <= self._SR_DEAD_HIGH:
            return self._SR_SNAP
        return sr

    def configure(self, cfg: PanoramaConfig) -> None:
        if not self._sdr:
            raise RuntimeError("RTL-SDR не подключён.")

        self._cfg = cfg
        span = cfg.stop_freq_hz - cfg.start_freq_hz

        if span <= self._USABLE_BW:
            sr = self._safe_sr(int(np.clip(span * 1.15, 250_000, self._SAFE_SR)))
            self._sdr.center_freq = int((cfg.start_freq_hz + cfg.stop_freq_hz) / 2)
        else:
            sr = self._SAFE_SR
            self._sdr.center_freq = int(cfg.start_freq_hz + sr / 2)

        self._sdr.sample_rate = sr

        if cfg.use_agc:
            self._sdr.gain = 'AUTO'
        else:
            self._sdr.gain = cfg.sdr_gain_db

    def capture_spectrum(self) -> Spectrum:
        if not self._sdr or not self._cfg:
            raise RuntimeError("RTL-SDR не настроен")

        cfg = self._cfg
        span = cfg.stop_freq_hz - cfg.start_freq_hz

        if span <= self._USABLE_BW:
            return self._capture_single(cfg.start_freq_hz, cfg.stop_freq_hz, cfg)
        return self._capture_sweep(cfg)

    def _capture_single(self, start_hz: float, stop_hz: float,
                        cfg: PanoramaConfig) -> Spectrum:
        try:
            self._sdr.read_bytes(1024 * 16)
        except Exception:
            pass

        window = np.hanning(cfg.fft_size)
        avg_power = np.zeros(cfg.fft_size, dtype=np.float64)
        max_power = np.full(cfg.fft_size, -np.inf, dtype=np.float64)
        valid_count = 0

        for _ in range(cfg.averaging_count):
            time.sleep(0.01)
            try:
                raw = self._sdr.read_samples(cfg.fft_size)
            except Exception as e:
                raise RuntimeError(f"Ошибка чтения сэмплов: {e}")
            if len(raw) < cfg.fft_size:
                # RTL-SDR вернул неполный буфер; остальные итерации тоже не помогут
                break
            raw_arr = np.array(raw)
            raw_arr -= raw_arr.mean()   # DC-block: убираем LO-утечку RTL-SDR
            fft_vals = np.fft.fftshift(np.fft.fft(raw_arr * window))
            power = np.abs(fft_vals) ** 2
            avg_power += power
            np.maximum(max_power, power, out=max_power)
            valid_count += 1

        if valid_count == 0:
            raise RuntimeError("RTL-SDR вернул неполные данные — проверьте подключение устройства")

        power_sel = max_power if cfg.use_max_hold else avg_power / valid_count
        db_vals = 10 * np.log10(power_sel + 1e-12) + cfg.calibration_offset_db

        sr = self._sdr.sample_rate
        freqs = np.fft.fftshift(np.fft.fftfreq(cfg.fft_size, d=1.0 / sr))
        freqs += self._sdr.center_freq

        mask = (freqs >= start_hz) & (freqs <= stop_hz)
        return Spectrum(
            frequencies_hz=freqs[mask],
            amplitudes_db=db_vals[mask],
            rbw_hz=sr / cfg.fft_size,
            timestamp=time.time(),
        )

    def _capture_sweep(self, cfg: PanoramaConfig) -> Spectrum:
        sr = self._SAFE_SR
        step = self._USABLE_BW

        centers = []
        c = cfg.start_freq_hz + sr / 2
        while c - sr / 2 < cfg.stop_freq_hz:
            centers.append(c)
            c += step

        all_freqs = []
        all_db = []

        for center in centers:
            self._sdr.center_freq = int(center)
            time.sleep(0.05)

            step_start = max(center - step / 2, cfg.start_freq_hz)
            step_stop  = min(center + step / 2, cfg.stop_freq_hz)

            chunk = self._capture_single(step_start, step_stop, cfg)
            all_freqs.append(chunk.frequencies_hz)
            all_db.append(chunk.amplitudes_db)

        freqs_all = np.concatenate(all_freqs)
        db_all    = np.concatenate(all_db)

        order = np.argsort(freqs_all)
        return Spectrum(
            frequencies_hz=freqs_all[order],
            amplitudes_db=db_all[order],
            rbw_hz=sr / cfg.fft_size,
            timestamp=time.time(),
        )
