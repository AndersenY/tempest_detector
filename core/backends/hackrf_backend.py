import time
import threading
import numpy as np
from ctypes import cast, POINTER, c_byte
import hackrf as _hackrf
from hackrf import HackRF, libhackrf
from .base import BaseInstrument
from ..config import PanoramaConfig
from ..models import Spectrum


class HackRfBackend(BaseInstrument):
    """HackRF One бэкенд.

    Требует: pip install pyhackrf  (устанавливается как модуль hackrf)
    Частоты:    1 МГц — 6 ГГц
    Sample rate: 1 МГц — 20 МГц
    LNA gain:   0, 8, 16, 24, 32, 40 дБ (фиксирован на _DEFAULT_LNA_GAIN)
    VGA gain:   0–62 дБ шаг 2 дБ  (задаётся через cfg.sdr_gain_db)

    Вместо pyhackrf.read_samples() используется собственный callback
    с threading.Event — это устраняет HACKRF_ERROR_BUSY (-6) и
    позволяет чисто прерывать захват при остановке потока.
    """

    _SAFE_SR       = 20_000_000   # 20 МГц — максимальный стабильный SR
    _USABLE_BW     = 17_000_000   # порог одиночного захвата (live)
    _SWEEP_STEP_BW = 15_000_000   # шаг sweep — плоская зона АЧХ тюнера

    _DEFAULT_LNA_GAIN = 24        # дБ (кратно 8: 0, 8, 16, 24, 32, 40)

    # Тайм-аут сбора одной порции сэмплов
    _COLLECT_TIMEOUT_S = 3.0
    # Пауза после hackrf_stop_rx перед следующим hackrf_start_rx
    _STOP_DELAY_S      = 0.05

    def __init__(self, device_index: int = 0):
        self._device: HackRF | None = None
        self._device_index = device_index
        self._cfg: PanoramaConfig | None = None

        # --- Состояние собственного RX callback ---
        self._rx_lock    = threading.Lock()
        self._rx_buffer  = bytearray()
        self._rx_needed  = 0
        self._rx_done    = threading.Event()
        self._rx_abort   = threading.Event()
        # Ссылка на ctypes-callback: без неё GC уничтожит объект во время стриминга
        self._c_rx_cb    = None
        self._streaming  = False

    # ------------------------------------------------------------------
    # BaseInstrument interface
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
                "Проверьте подключение и убедитесь, что устройство не занято другой программой."
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
    # Собственный RX callback (заменяет pyhackrf.read_samples)
    # ------------------------------------------------------------------

    def _rx_callback(self, transfer_ptr) -> int:
        """Вызывается из потока libhackrf при каждом USB-трансфере."""
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

    def _start_streaming(self) -> None:
        if self._streaming or self._device is None:
            return
        self._c_rx_cb = _hackrf._callback(self._rx_callback)
        result = libhackrf.hackrf_start_rx(self._device.dev_p, self._c_rx_cb, None)
        if result != 0:
            raise RuntimeError(f"hackrf_start_rx: код ошибки {result}")
        self._streaming = True

    def _stop_streaming(self, wait: bool = True) -> None:
        if not self._streaming or self._device is None:
            return
        self._rx_abort.set()          # сигнал callback'у: не накапливать
        libhackrf.hackrf_stop_rx(self._device.dev_p)
        if wait:
            # Дождаться полной остановки USB-трансфера
            deadline = time.perf_counter() + 0.5
            while time.perf_counter() < deadline:
                if libhackrf.hackrf_is_streaming(self._device.dev_p) != 1:
                    break
                time.sleep(0.01)
            time.sleep(self._STOP_DELAY_S)
        self._streaming = False
        self._rx_abort.clear()

    def _collect_samples(self, num_samples: int) -> np.ndarray:
        """Собрать num_samples IQ-сэмплов из активного стриминга.

        threading.Event гарантирует возврат за _COLLECT_TIMEOUT_S секунд
        в любых условиях — поток LiveWorker не зависает при остановке.
        """
        num_bytes = num_samples * 2
        with self._rx_lock:
            self._rx_buffer = bytearray()
            self._rx_needed = num_bytes
        self._rx_done.clear()
        self._rx_abort.clear()

        self._start_streaming()

        if not self._rx_done.wait(timeout=self._COLLECT_TIMEOUT_S):
            # Тайм-аут: прерываем и бросаем ошибку
            self._rx_abort.set()
            raise RuntimeError(
                f"HackRF: тайм-аут {self._COLLECT_TIMEOUT_S:.0f} с при сборе сэмплов"
            )

        with self._rx_lock:
            data = bytes(self._rx_buffer[:num_bytes])

        # bytes2iq: int8 → complex128, нормирование к ±1
        values = np.frombuffer(data, dtype=np.int8).astype(np.float64)
        iq = values.view(np.complex128) / 127.5
        return iq

    # ------------------------------------------------------------------
    # Вспомогательные методы конфигурации
    # ------------------------------------------------------------------

    def _use_single(self, cfg: PanoramaConfig) -> bool:
        fast = cfg.averaging_count <= 1 and not cfg.use_max_hold
        span = cfg.stop_freq_hz - cfg.start_freq_hz
        threshold = self._USABLE_BW if fast else self._SWEEP_STEP_BW
        return span <= threshold

    @staticmethod
    def _snap_vga(gain_db: float) -> int:
        """Ближайший допустимый VGA gain (чётные 0–62 дБ)."""
        return int(np.clip(round(gain_db / 2) * 2, 0, 62))

    @staticmethod
    def _snap_lna(gain_db: float) -> int:
        """Ближайший допустимый LNA gain (кратно 8, 0–40 дБ)."""
        return int(np.clip(round(gain_db / 8) * 8, 0, 40))

    def configure(self, cfg: PanoramaConfig) -> None:
        if not self._device:
            raise RuntimeError("HackRF не подключён.")

        # Останавливаем стриминг перед изменением частоты/SR/gain
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
        if cfg.sdr_gain_db > 50:
            self._device.enable_amp()
        else:
            self._device.disable_amp()

        # Запускаем стриминг заранее — первый захват не теряет время на старт RX
        self._start_streaming()

    # ------------------------------------------------------------------
    # Захват спектра
    # ------------------------------------------------------------------

    _SWEEP_SETTLE_S        = 0.05
    _SWEEP_SETTLE_FAST_S   = 0.05
    _CAPTURE_SETTLE_S      = 0.010
    _CAPTURE_SETTLE_FAST_S = 0.010

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
            raw_arr -= raw_arr.mean()   # DC-block
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
        settle_s = self._SWEEP_SETTLE_FAST_S if fast else self._SWEEP_SETTLE_S

        centers = []
        c = cfg.start_freq_hz + step / 2
        while c - step / 2 < cfg.stop_freq_hz:
            centers.append(c)
            c += step

        all_freqs: list[np.ndarray] = []
        all_db:    list[np.ndarray] = []

        for center in centers:
            # Смена частоты требует перезапуска стриминга
            self._stop_streaming()
            self._device.sample_rate = self._SAFE_SR
            self._device.center_freq = int(center)
            time.sleep(settle_s)
            self._start_streaming()

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
