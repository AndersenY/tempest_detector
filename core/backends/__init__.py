from .base import BaseInstrument
from .demo_backend import DemoSimulator

try:
    from .rtlsdr_backend import RtlSdrBackend
except ImportError:
    RtlSdrBackend = None  # type: ignore[assignment,misc]

try:
    from .hackrf_backend import HackRfBackend
except ImportError:
    HackRfBackend = None  # type: ignore[assignment,misc]

__all__ = ["BaseInstrument", "RtlSdrBackend", "DemoSimulator", "HackRfBackend"]
