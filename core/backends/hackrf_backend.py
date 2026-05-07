import os
import sys
import time
import threading
import numpy as np
from ctypes import (CDLL, CFUNCTYPE, Structure, POINTER, cast, pointer,
                    c_int, c_uint8, c_uint32, c_uint64, c_double,
                    c_void_p, c_byte, addressof)
from .base import BaseInstrument
from ..config import PanoramaConfig
from ..models import Spectrum


# ------------------------------------------------------------------
# Загрузка hackrf.dll (Windows) или libhackrf.so (Linux/macOS)
# ------------------------------------------------------------------
def _load_hackrf_lib():
    if sys.platform == "win32":
        # Сначала ищем рядом с этим файлом /../lib/hackrf.dll
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "..", "lib", "hackrf-0.dll"),
            "hackrf.dll",
        ]
        for path in candidates:
            path = os.path.normpath(path)
            if os.path.isfile(path):
                # os.add_dll_directory нужен для transitive-зависимостей (libusb-1.0.dll)
                lib_dir = os.path.dirname(path)
                if lib_dir:
                    os.add_dll_directory(lib_dir)
                return CDLL(path)
        raise OSError(
            "hackrf.dll не найден. Положите hackrf.dll и libusb-1.0.dll "
            "в папку lib/ рядом с проектом."
        )
    else:
        for name in ("libhackrf.so.0", "libhackrf.so"):
            try:
                return CDLL(name)
            except OSError:
                continue
        raise OSError(
            "libhackrf.so не найден. Установите: sudo apt install libhackrf-dev")


_lib = _load_hackrf_lib()

# ------------------------------------------------------------------
# Прототипы функций
# ------------------------------------------------------------------
_p_dev = c_void_p

_lib.hackrf_init.restype = c_int
_lib.hackrf_exit.restype = c_int
_lib.hackrf_open.argtypes = [POINTER(_p_dev)]
_lib.hackrf_open.restype = c_int
_lib.hackrf_close.argtypes = [_p_dev]
_lib.hackrf_close.restype = c_int
_lib.hackrf_set_freq.argtypes = [_p_dev, c_uint64]
_lib.hackrf_set_freq.restype = c_int
_lib.hackrf_set_sample_rate.argtypes = [_p_dev, c_double]
_lib.hackrf_set_sample_rate.restype = c_int
_lib.hackrf_set_amp_enable.argtypes = [_p_dev, c_uint8]
_lib.hackrf_set_amp_enable.restype = c_int
_lib.hackrf_set_lna_gain.argtypes = [_p_dev, c_uint32]
_lib.hackrf_set_lna_gain.restype = c_int
_lib.hackrf_set_vga_gain.argtypes = [_p_dev, c_uint32]
_lib.hackrf_set_vga_gain.restype = c_int
_lib.hackrf_is_streaming.argtypes = [_p_dev]
_lib.hackrf_is_streaming.restype = c_int


class _HackRFTransfer(Structure):
    _fields_ = [
        ("device",        c_void_p),
        ("buffer",        POINTER(c_byte)),
        ("buffer_length", c_int),
        ("valid_length",  c_int),
        ("rx_ctx",        c_void_p),
        ("tx_ctx",        c_void_p),
    ]


_rx_cb_t = CFUNCTYPE(c_int, POINTER(_HackRFTransfer))

_lib.hackrf_start_rx.argtypes = [_p_dev, _rx_cb_t, c_void_p]
_lib.hackrf_start_rx.restype = c_int
_lib.hackrf_stop_rx.argtypes = [_p_dev]
_lib.hackrf_stop_rx.restype = c_int

HACKRF_SUCCESS = 0
HACKRF_ERROR_BUSY = -6


# ------------------------------------------------------------------
# Бэкенд
# ------------------------------------------------------------------
class HackRfBackend(BaseInstrument):
    """HackRF One бэкенд — кросс-платформенный (Windows/Linux) через ctypes."""

    _SAFE_SR = 20_000_000
    _USABLE_BW = 17_000_000
    _SWEEP_STEP_BW = 15_000_000
    _DEFAULT_LNA_GAIN = 24

    _COLLECT_TIMEOUT_S = 3.0
    _COLLECT_MAX_RETRIES = 2
    _PLL_SETTLE_MS = 8

    def __init__(self, device_index: int = 0):
        self._dev_p = _p_dev(None)   # указатель на устройство
        self._device_index = device_index
        self._cfg: PanoramaConfig | None = None

        # Параметры, выставляемые через configure()
        self._sample_rate = self._SAFE_SR
        self._center_freq = 100_000_000
        self._lna_gain = self._DEFAULT_LNA_GAIN
        self._vga_gain = 16
        self._amp_enabled = False

        self._rx_lock = threading.Lock()
        self._rx_buffer = bytearray()
        self._rx_needed = 0
        self._rx_done = threading.Event()
        self._rx_abort = threading.Event()
        self._c_rx_cb = None
        self._streaming = False
        self._closing = False
        self._initialized = False

    # ------------------------------------------------------------------
    # BaseInstrument interface
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return f"HackRF One (устройство {self._device_index})"

    @property
    def is_connected(self) -> bool:
        return self._dev_p.value is not None

    def connect(self) -> None:
        if self.is_connected:
            self.close()
        if not self._initialized:
            if _lib.hackrf_init() != HACKRF_SUCCESS:
                raise RuntimeError("hackrf_init() завершился с ошибкой")
            self._initialized = True
        res = _lib.hackrf_open(pointer(self._dev_p))
        if res != HACKRF_SUCCESS:
            raise RuntimeError(
                f"hackrf_open() завершился с ошибкой: код {res}")
        self._closing = False
        print("✅ HackRF One подключён")

    def close(self) -> None:
        if not self.is_connected:
            return
        print("🔌 HackRF: завершение сессии...")
        self._stop_streaming(wait=True)
        try:
            _lib.hackrf_close(self._dev_p)
            print("✅ HackRF: сессия завершена.")
        except Exception as e:
            print(f"⚠️ Ошибка закрытия HackRF: {e}")
        finally:
            self._dev_p = _p_dev(None)
            self._streaming = False
            self._closing = True
            self._rx_done.clear()
            self._rx_abort.clear()
        if self._initialized:
            try:
                _lib.hackrf_exit()
            except Exception:
                pass
            self._initialized = False

    # ------------------------------------------------------------------
    # Внутренние методы: streaming & callback
    # ------------------------------------------------------------------
    def _rx_callback(self, transfer_ptr) -> int:
        if self._closing or self._rx_abort.is_set() or self._rx_done.is_set():
            return 0
        try:
            t = transfer_ptr.contents
            n = t.valid_length
            if n <= 0:
                return 0
            values = cast(t.buffer, POINTER(c_byte * n)).contents
            with self._rx_lock:
                needed = self._rx_needed - len(self._rx_buffer)
                if needed > 0:
                    take = min(n, needed)
                    self._rx_buffer.extend(bytearray(values)[:take])
                    if len(self._rx_buffer) >= self._rx_needed:
                        self._rx_done.set()
        except Exception:
            pass
        return 0

    def _start_streaming(self) -> None:
        if not self.is_connected or self._closing:
            return
        if _lib.hackrf_is_streaming(self._dev_p) == 1 and self._streaming:
            return
        self._streaming = False
        if self._c_rx_cb is None:
            self._c_rx_cb = _rx_cb_t(self._rx_callback)
        res = _lib.hackrf_start_rx(self._dev_p, self._c_rx_cb, None)
        if res == HACKRF_ERROR_BUSY:
            time.sleep(0.05)
            res = _lib.hackrf_start_rx(self._dev_p, self._c_rx_cb, None)
        if res != HACKRF_SUCCESS:
            raise RuntimeError(f"hackrf_start_rx failed: код {res}")
        self._streaming = True

    def _stop_streaming(self, wait: bool = True) -> None:
        if not self._streaming or not self.is_connected:
            return
        self._closing = True
        self._rx_abort.set()
        try:
            _lib.hackrf_stop_rx(self._dev_p)
        except Exception:
            pass
        if wait:
            deadline = time.perf_counter() + 1.0
            while time.perf_counter() < deadline:
                try:
                    if _lib.hackrf_is_streaming(self._dev_p) != 1:
                        break
                except Exception:
                    break
                time.sleep(0.02)
        self._c_rx_cb = None
        self._streaming = False
        self._rx_abort.clear()
        self._rx_done.clear()
        self._closing = False

    def _apply_hw_settings(self) -> None:
        """Отправить текущие параметры на устройство."""
        _lib.hackrf_set_sample_rate(self._dev_p, float(self._sample_rate))
        _lib.hackrf_set_freq(self._dev_p, int(self._center_freq))
        _lib.hackrf_set_lna_gain(self._dev_p, int(self._lna_gain))
        _lib.hackrf_set_vga_gain(self._dev_p, int(self._vga_gain))
        _lib.hackrf_set_amp_enable(
            self._dev_p, c_uint8(1 if self._amp_enabled else 0))

    def _collect_samples(self, num_samples: int) -> np.ndarray:
        num_bytes = num_samples * 2
        with self._rx_lock:
            self._rx_buffer.clear()
            self._rx_needed = num_bytes
        self._rx_done.clear()
        self._rx_abort.clear()
        self._closing = False

        self._start_streaming()
        if _lib.hackrf_is_streaming(self._dev_p) != 1:
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
        raw = np.frombuffer(data, dtype=np.int8).astype(np.float64)
        return (raw[0::2] + 1j * raw[1::2]) / 127.5

    # ------------------------------------------------------------------
    # Конфигурация и захват
    # ------------------------------------------------------------------
    @staticmethod
    def _snap_vga(g): return int(np.clip(round(g / 2) * 2, 0, 62))
    @staticmethod
    def _snap_lna(g): return int(np.clip(round(g / 8) * 8, 0, 40))

    def _use_single(self, cfg: PanoramaConfig) -> bool:
        fast = cfg.averaging_count <= 1 and not cfg.use_max_hold
        span = cfg.stop_freq_hz - cfg.start_freq_hz
        threshold = self._USABLE_BW if fast else self._SWEEP_STEP_BW
        return span <= threshold

    def configure(self, cfg: PanoramaConfig) -> None:
        if not self.is_connected:
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

        self._sample_rate = sr
        self._center_freq = center
        self._lna_gain = self._snap_lna(self._DEFAULT_LNA_GAIN)
        self._vga_gain = self._snap_vga(cfg.sdr_gain_db)
        self._amp_enabled = cfg.sdr_gain_db > 50

        self._apply_hw_settings()
        self._start_streaming()

    _SWEEP_SETTLE_S = 0.010
    _SWEEP_SETTLE_FAST_S = 0.010
    _CAPTURE_SETTLE_S = 0.0
    _CAPTURE_SETTLE_FAST_S = 0.0

    def capture_spectrum(self) -> Spectrum:
        if not self.is_connected or not self._cfg:
            raise RuntimeError("HackRF не настроен")
        cfg = self._cfg
        fast = cfg.averaging_count <= 1 and not cfg.use_max_hold
        if self._use_single(cfg):
            return self._capture_single(cfg.start_freq_hz, cfg.stop_freq_hz, cfg, fast)
        return self._capture_sweep(cfg, fast)

    def _capture_single(self, start_hz, stop_hz, cfg, fast=False):
        settle = self._CAPTURE_SETTLE_FAST_S if fast else self._CAPTURE_SETTLE_S
        win = np.hanning(cfg.fft_size)
        avg = np.zeros(cfg.fft_size, dtype=np.float64)
        mx = np.full(cfg.fft_size, -np.inf, dtype=np.float64)
        cnt = 0
        for _ in range(cfg.averaging_count):
            time.sleep(settle)
            raw = self._collect_samples(cfg.fft_size)
            if len(raw) < cfg.fft_size:
                break
            raw -= raw.mean()
            p = np.abs(np.fft.fftshift(np.fft.fft(raw * win))) ** 2
            avg += p
            np.maximum(mx, p, out=mx)
            cnt += 1
        if cnt == 0:
            raise RuntimeError("HackRF: нет данных")
        power = mx if cfg.use_max_hold else avg / cnt
        db = 10 * np.log10(power + 1e-12) + cfg.calibration_offset_db
        freqs = (np.fft.fftshift(np.fft.fftfreq(cfg.fft_size, d=1.0 / self._sample_rate))
                 + self._center_freq)
        mask = (freqs >= start_hz) & (freqs <= stop_hz)
        return Spectrum(freqs[mask], db[mask], self._sample_rate / cfg.fft_size, time.time())

    def _capture_sweep(self, cfg, fast=False):
        step = self._SWEEP_STEP_BW
        settle = self._PLL_SETTLE_MS / 1000.0
        centers = []
        c = cfg.start_freq_hz + step / 2
        while c - step / 2 < cfg.stop_freq_hz:
            centers.append(c)
            c += step

        all_f, all_d = [], []
        for center in centers:
            self._center_freq = int(center)
            _lib.hackrf_set_freq(self._dev_p, int(center))
            time.sleep(settle)
            s = max(center - step / 2, cfg.start_freq_hz)
            e = min(center + step / 2, cfg.stop_freq_hz)
            ch = self._capture_single(s, e, cfg, fast)
            all_f.append(ch.frequencies_hz)
            all_d.append(ch.amplitudes_db)

        fa = np.concatenate(all_f)
        da = np.concatenate(all_d)
        order = np.argsort(fa)
        return Spectrum(fa[order], da[order], self._SAFE_SR / cfg.fft_size, time.time())
