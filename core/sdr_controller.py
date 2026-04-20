# Backward-compatibility shim. Используйте core.backends.RtlSdrBackend напрямую.
from .backends.rtlsdr_backend import RtlSdrBackend as SDRController

__all__ = ["SDRController"]
