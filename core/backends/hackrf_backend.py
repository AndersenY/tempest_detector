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
    """HackRF One бэкенд с гарантированно безопасным завершением.
    
    Устранены Segmentation fault при закрытии окна/сбросе.
    Callback полностью защищён от вызова после начала teardown.
    """

    _SAFE_SR         = 20_000_000
    _USABLE_BW       = 17_000_000
    _SWEEP_STEP_BW   = 15_000_000
    _DEFAULT_LNA_GAIN = 24

    _COLLECT_TIMEOUT_S   = 3.0
    _COLLECT_MAX_RETRIES = 2
    _PLL_SETTLE_MS       = 8

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
        self._closing    = False  # Флаг мгновенной блокировки callback'ов

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
            self._closing = False
            print("✅ HackRF One подключён")
        except Exception as e:
            raise RuntimeError(f"Не удалось подключить HackRF One: {e}")

    def close(self) -> None:
        """Безопасное завершение. Вызывается только из main_thread (closeEvent)."""
        if self._device is None:
            return
        print("🔌 HackRF: завершение сессии...")
        self._stop_streaming(wait=True)
        try:
            self._device.close()
            print("✅ HackRF: сессия завершена, диод RX погашен.")
        except Exception as e:
            print(f"⚠️ Ошибка закрытия HackRF: {e}")
        finally:
            self._device = None
            self._streaming = False
            self._closing = True
            self._rx_done.clear()
            self._rx_abort.clear()

    # ------------------------------------------------------------------
    # RX Callback & Streaming
    # ------------------------------------------------------------------
    def _rx_callback(self, transfer_ptr) -> int:
        """Вызывается из потока libhackrf. Мгновенно выходит при _closing."""
        if self._closing or self._rx_abort.is_set() or self._rx_done.is_set():
            return 0
        try:
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
            return 0

    def _start_streaming(self) -> None:
        if self._device is None or self._closing:
            return
        hw = libhackrf.hackrf_is_streaming(self._device.dev_p)
        if hw == 1 and self._streaming:
            return

        self._streaming = False
        if self._c_rx_cb is None:
            self._c_rx_cb = _hackrf._callback(self._rx_callback)

        res = libhackrf.hackrf_start_rx(self._device.dev_p, self._c_rx_cb, None)
        if res == -6:  # HACKRF_ERROR_BUSY
            time.sleep(0.05)
            res = libhackrf.hackrf_start_rx(self._device.dev_p, self._c_rx_cb, None)
        if res != 0:
            raise RuntimeError(f"hackrf_start_rx failed: код {res}")
        self._streaming = True

    def _stop_streaming(self, wait: bool = True) -> None:
        if not self._streaming or self._device is None:
            return
        # 1. Мгновенно блокируем callback
        self._closing = True
        self._rx_abort.set()
        
        # 2. ОБЯЗАТЕЛЬНО обнуляем ссылку ДО вызова stop_rx
        self._c_rx_cb = None

        # 3. Останавливаем RX
        try:
            libhackrf.hackrf_stop_rx(self._device.dev_p)
        except Exception:
            pass

        # 4. Ждём подтверждения от MCU
        if wait:
            deadline = time.perf_counter() + 1.0
            while time.perf_counter() < deadline:
                try:
                    if libhackrf.hackrf_is_streaming(self._device.dev_p) != 1:
                        break
                except Exception:
                    break
                time.sleep(0.02)

        self._streaming = False
        self._rx_abort.clear()
        self._rx_done.clear()
        self._closing = False

    def _collect_samples(self, num_samples: int) -> np.ndarray:
        num_bytes = num_samples * 2
        with self._rx_lock:
            self._rx_buffer.clear()
            self._rx_needed = num_bytes
        self._rx_done.clear()
        self._rx_abort.clear()
        self._closing = False  # Разрешаем callback только на время сбора

        self._start_streaming()
        if libhackrf.hackrf_is_streaming(self._device.dev_p) != 1:
            self._streaming = False
            self._start_streaming()

        for _ in range(self._COLLECT_MAX_RETRIES):
            if self._rx_done.wait(timeout=self._COLLECT_TIMEOUT_S):
                break
            self._stop_streaming(wait=False)
            time.sleep(0.1)
            self._start_streaming()
        else:
            self._rx_abort.set()
            raise RuntimeError(f"HackRF: тайм-аут {self._COLLECT_TIMEOUT_S} с")

        with self._rx_lock:
            data = bytes(self._rx_buffer[:num_bytes])
        return np.frombuffer(data, dtype=np.int8).astype(np.float64).view(np.complex128) / 127.5

    # ------------------------------------------------------------------
    # Конфигурация и захват
    # ------------------------------------------------------------------
    def _use_single(self, cfg: PanoramaConfig) -> bool:
        fast = cfg.averaging_count <= 1 and not cfg.use_max_hold
        span = cfg.stop_freq_hz - cfg.start_freq_hz
        threshold = self._USABLE_BW if fast else self._SWEEP_STEP_BW
        return span <= threshold

    @staticmethod
    def _snap_vga(g): return int(np.clip(round(g / 2) * 2, 0, 62))
    @staticmethod
    def _snap_lna(g): return int(np.clip(round(g / 8) * 8, 0, 40))

    def configure(self, cfg: PanoramaConfig) -> None:
        if not self._device: raise RuntimeError("HackRF не подключён.")
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

    _SWEEP_SETTLE_S = 0.010; _SWEEP_SETTLE_FAST_S = 0.010
    # Settle между усреднениями одной частоты = 0: стриминг непрерывен,
    # перенастройки нет, задержка только увеличивает окно усреднения без пользы.
    _CAPTURE_SETTLE_S = 0.0; _CAPTURE_SETTLE_FAST_S = 0.0

    def capture_spectrum(self) -> Spectrum:
        if not self._device or not self._cfg: raise RuntimeError("HackRF не настроен")
        cfg = self._cfg
        fast = cfg.averaging_count <= 1 and not cfg.use_max_hold
        return self._capture_single(cfg.start_freq_hz, cfg.stop_freq_hz, cfg, fast) if self._use_single(cfg) else self._capture_sweep(cfg, fast)

    def _capture_single(self, start_hz, stop_hz, cfg, fast=False):
        settle = self._CAPTURE_SETTLE_FAST_S if fast else self._CAPTURE_SETTLE_S
        win = np.hanning(cfg.fft_size)
        avg, mx, cnt = np.zeros(cfg.fft_size, dtype=np.float64), np.full(cfg.fft_size, -np.inf, dtype=np.float64), 0
        for _ in range(cfg.averaging_count):
            time.sleep(settle)
            raw = self._collect_samples(cfg.fft_size)
            if len(raw) < cfg.fft_size: break
            raw -= raw.mean()
            p = np.abs(np.fft.fftshift(np.fft.fft(raw * win)))**2
            avg += p; np.maximum(mx, p, out=mx); cnt += 1
        if cnt == 0: raise RuntimeError("HackRF: нет данных")
        db = 10*np.log10((mx if cfg.use_max_hold else avg/cnt)+1e-12)+cfg.calibration_offset_db
        sr = self._device.sample_rate
        f = np.fft.fftshift(np.fft.fftfreq(cfg.fft_size, d=1.0/sr))+self._device.center_freq
        m = (f>=start_hz)&(f<=stop_hz)
        return Spectrum(f[m], db[m], sr/cfg.fft_size, time.time())

    def _capture_sweep(self, cfg, fast=False):
        step = self._SWEEP_STEP_BW; settle = self._PLL_SETTLE_MS/1000.0
        centers, c = [], cfg.start_freq_hz+step/2
        while c-step/2 < cfg.stop_freq_hz: centers.append(c); c += step
        af, ad = [], []
        for center in centers:
            self._device.center_freq = int(center); time.sleep(settle)
            s, e = max(center-step/2, cfg.start_freq_hz), min(center+step/2, cfg.stop_freq_hz)
            ch = self._capture_single(s, e, cfg, fast); af.append(ch.frequencies_hz); ad.append(ch.amplitudes_db)
        fa, da = np.concatenate(af), np.concatenate(ad)
        return Spectrum(fa[np.argsort(fa)], da[np.argsort(fa)], self._SAFE_SR/cfg.fft_size, time.time())