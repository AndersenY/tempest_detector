import time
import threading
import numpy as np
from ctypes import cast, POINTER, c_byte
import hackrf as _hackrf
from hackrf import HackRF, libhackrf
from .base import BaseInstrument
from ..config import PanoramaConfig
from ..models import Spectrum

_IS_STREAMING = 1


class HackRfBackend(BaseInstrument):
    """HackRF One бэкенд.
    Требует: pip install pyhackrf
    Частоты:    1 МГц — 6 ГГц
    Sample rate: 1 МГц — 20 МГц
    LNA gain:   0, 8, 16, 24, 32, 40 дБ
    VGA gain:   0–62 дБ шаг 2 дБ

    Реализует собственный RX callback с автовосстановлением потока
    и защитой от исключений, что устраняет зависания и тайм-ауты.
    """

    _SAFE_SR       = 20_000_000
    _USABLE_BW     = 17_000_000
    _SWEEP_STEP_BW = 15_000_000
    _DEFAULT_LNA_GAIN = 24

    _COLLECT_TIMEOUT_S = 3.0      # тайм-аут одной порции (сек)
    _COLLECT_MAX_RETRIES = 2      # повторов при тайм-ауте
    _PLL_SETTLE_MS     = 8        # ожидание PLL после смены частоты

    def __init__(self, device_index: int = 0):
        self._device: HackRF | None = None
        self._device_index = device_index
        self._cfg: PanoramaConfig | None = None

        self._rx_lock    = threading.Lock()
        self._rx_buffer  = bytearray()
        self._rx_needed  = 0
        self._rx_done    = threading.Event()
        self._rx_abort   = threading.Event()
        self._c_rx_cb    = None
        self._streaming  = False

    # ------------------------------------------------------------------
    # BaseInstrument
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return f"HackRF One (устройство {self._device_index})"

    @property
    def is_connected(self) -> bool:
        return self._device is not None

    def connect(self) -> None:
        try:
            if self._device:
                self.close()
            self._device = HackRF(device_index=self._device_index)
            print("✅ HackRF One подключён")
        except Exception as e:
            raise RuntimeError(
                f"Не удалось подключить HackRF One: {e}. "
                "Проверьте подключение и убедитесь, что устройство не занято."
            )

    def close(self) -> None:
        if self._device is not None:
            self._stop_streaming()
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    # ------------------------------------------------------------------
    # RX Callback & Streaming
    # ------------------------------------------------------------------
    def _rx_callback(self, transfer_ptr) -> int:
        """Вызывается из потока libhackrf. Любое исключение здесь убивает RX-поток."""
        try:
            if self._rx_abort.is_set() or self._rx_done.is_set():
                return 0
            c = transfer_ptr.contents
            n = c.buffer_length
            values = cast(c.buffer, POINTER(c_byte * n)).contents
            with self._rx_lock:
                needed = self._rx_needed - len(self._rx_buffer)
                if needed > 0:
                    take = min(n, needed)
                    self._rx_buffer.extend(bytearray(values)[:take])
                    if len(self._rx_buffer) >= self._rx_needed:
                        self._rx_done.set()
            return 0
        except Exception:
            # Критически важно: callback не должен бросать исключения
            return 0

    def _start_streaming(self) -> None:
        if self._device is None:
            return
        # Синхронизация с железом
        hw_status = libhackrf.hackrf_is_streaming(self._device.dev_p)
        if hw_status == _IS_STREAMING and self._streaming:
            return  # Уже работает

        self._streaming = False
        if self._c_rx_cb is None:
            self._c_rx_cb = _hackrf._callback(self._rx_callback)

        result = libhackrf.hackrf_start_rx(self._device.dev_p, self._c_rx_cb, None)
        if result == -6:  # HACKRF_ERROR_BUSY
            time.sleep(0.05)
            result = libhackrf.hackrf_start_rx(self._device.dev_p, self._c_rx_cb, None)

        if result != 0:
            raise RuntimeError(f"hackrf_start_rx failed: код {result}")
        self._streaming = True

    def _stop_streaming(self, wait: bool = True) -> None:
        if not self._streaming or self._device is None:
            return
        self._rx_abort.set()
        libhackrf.hackrf_stop_rx(self._device.dev_p)
        if wait:
            deadline = time.perf_counter() + 0.5
            while time.perf_counter() < deadline:
                if libhackrf.hackrf_is_streaming(self._device.dev_p) != _IS_STREAMING:
                    break
                time.sleep(0.01)
        self._streaming = False
        self._rx_abort.clear()
        self._rx_done.clear()

    def _collect_samples(self, num_samples: int) -> np.ndarray:
        """Сбор сэмплов с автовосстановлением при обрыве USB-потока."""
        num_bytes = num_samples * 2
        with self._rx_lock:
            self._rx_buffer.clear()
            self._rx_needed = num_bytes
        self._rx_done.clear()
        self._rx_abort.clear()

        self._start_streaming()

        # Проверка реального статуса потока перед ожиданием
        if libhackrf.hackrf_is_streaming(self._device.dev_p) != _IS_STREAMING:
            self._streaming = False
            self._start_streaming()

        for attempt in range(self._COLLECT_MAX_RETRIES):
            if self._rx_done.wait(timeout=self._COLLECT_TIMEOUT_S):
                break
            # Тайм-аут: принудительный рестарт потока
            self._stop_streaming(wait=False)
            time.sleep(0.1)
            self._start_streaming()
        else:
            self._rx_abort.set()
            raise RuntimeError(
                f"HackRF: тайм-аут {self._COLLECT_TIMEOUT_S:.0f} с при сборе сэмплов "
                f"({self._COLLECT_MAX_RETRIES} попыток). Проверьте USB-кабель, питание или уменьшите fft_size."
            )

        with self._rx_lock:
            data = bytes(self._rx_buffer[:num_bytes])

        values = np.frombuffer(data, dtype=np.int8).astype(np.float64)
        iq = values.view(np.complex128) / 127.5
        return iq

    # ------------------------------------------------------------------
    # Конфигурация
    # ------------------------------------------------------------------
    def _use_single(self, cfg: PanoramaConfig) -> bool:
        fast = cfg.averaging_count <= 1 and not cfg.use_max_hold
        span = cfg.stop_freq_hz - cfg.start_freq_hz
        threshold = self._USABLE_BW if fast else self._SWEEP_STEP_BW
        return span <= threshold

    @staticmethod
    def _snap_vga(gain_db: float) -> int:
        return int(np.clip(round(gain_db / 2) * 2, 0, 62))

    @staticmethod
    def _snap_lna(gain_db: float) -> int:
        return int(np.clip(round(gain_db / 8) * 8, 0, 40))

    def configure(self, cfg: PanoramaConfig) -> None:
        if not self._device:
            raise RuntimeError("HackRF не подключён.")

        self._stop_streaming()
        self._cfg = cfg
        span = cfg.stop_freq_hz - cfg.start_freq_hz

        if self._use_single(cfg):
            sr = max(1_000_000, round(span * 1.2 / 1_000_000) * 1_000_000)
            sr = int(np.clip(sr, 1_000_000, self._SAFE_SR))
            center = int((cfg.start_freq_hz + cfg.stop_freq_hz) / 2)
        else:
            sr = self._SAFE_SR
            center = int(cfg.start_freq_hz + self._SWEEP_STEP_BW / 2)

        self._device.sample_rate = sr
        self._device.center_freq = center
        self._device.lna_gain    = self._snap_lna(self._DEFAULT_LNA_GAIN)
        self._device.vga_gain    = self._snap_vga(cfg.sdr_gain_db)
        self._device.enable_amp() if cfg.sdr_gain_db > 50 else self._device.disable_amp()

        self._start_streaming()

    # ------------------------------------------------------------------
    # Захват спектра
    # ------------------------------------------------------------------
    _SWEEP_SETTLE_S        = 0.010
    _SWEEP_SETTLE_FAST_S   = 0.010
    _CAPTURE_SETTLE_S      = 0.005
    _CAPTURE_SETTLE_FAST_S = 0.005

    def capture_spectrum(self) -> Spectrum:
        if not self._device or not self._cfg:
            raise RuntimeError("HackRF не настроен")

        cfg = self._cfg
        fast = cfg.averaging_count <= 1 and not cfg.use_max_hold

        if self._use_single(cfg):
            return self._capture_single(cfg.start_freq_hz, cfg.stop_freq_hz, cfg, fast=fast)
        return self._capture_sweep(cfg, fast=fast)

    def _capture_single(self, start_hz: float, stop_hz: float,
                        cfg: PanoramaConfig, fast: bool = False) -> Spectrum:
        settle_s = self._CAPTURE_SETTLE_FAST_S if fast else self._CAPTURE_SETTLE_S

        window    = np.hanning(cfg.fft_size)
        avg_power = np.zeros(cfg.fft_size, dtype=np.float64)
        max_power = np.full(cfg.fft_size, -np.inf, dtype=np.float64)
        valid_count = 0

        for _ in range(cfg.averaging_count):
            time.sleep(settle_s)
            raw_arr = self._collect_samples(cfg.fft_size)
            if len(raw_arr) < cfg.fft_size:
                break
            raw_arr -= raw_arr.mean()
            fft_vals = np.fft.fftshift(np.fft.fft(raw_arr * window))
            power = np.abs(fft_vals) ** 2
            avg_power += power
            np.maximum(max_power, power, out=max_power)
            valid_count += 1

        if valid_count == 0:
            raise RuntimeError("HackRF: не удалось получить данные — проверьте подключение")

        power_sel = max_power if cfg.use_max_hold else avg_power / valid_count
        db_vals = 10 * np.log10(power_sel + 1e-12) + cfg.calibration_offset_db

        sr = self._device.sample_rate
        freqs = np.fft.fftshift(np.fft.fftfreq(cfg.fft_size, d=1.0 / sr))
        freqs += self._device.center_freq

        mask = (freqs >= start_hz) & (freqs <= stop_hz)
        return Spectrum(
            frequencies_hz=freqs[mask],
            amplitudes_db=db_vals[mask],
            rbw_hz=sr / cfg.fft_size,
            timestamp=time.time(),
        )

    def _capture_sweep(self, cfg: PanoramaConfig, fast: bool = False) -> Spectrum:
        step     = self._SWEEP_STEP_BW
        settle_ms = self._PLL_SETTLE_MS

        centers = []
        c = cfg.start_freq_hz + step / 2
        while c - step / 2 < cfg.stop_freq_hz:
            centers.append(c)
            c += step

        all_freqs: list[np.ndarray] = []
        all_db:    list[np.ndarray] = []

        for center in centers:
            self._device.center_freq = int(center)
            time.sleep(settle_ms / 1000.0)

            step_start = max(center - step / 2, cfg.start_freq_hz)
            step_stop  = min(center + step / 2, cfg.stop_freq_hz)
            chunk = self._capture_single(step_start, step_stop, cfg, fast=fast)
            all_freqs.append(chunk.frequencies_hz)
            all_db.append(chunk.amplitudes_db)

        freqs_all = np.concatenate(all_freqs)
        db_all    = np.concatenate(all_db)
        order = np.argsort(freqs_all)
        return Spectrum(
            frequencies_hz=freqs_all[order],
            amplitudes_db=db_all[order],
            rbw_hz=self._SAFE_SR / cfg.fft_size,
            timestamp=time.time(),
        )