from abc import ABC, abstractmethod
from ..config import PanoramaConfig
from ..models import Spectrum


class BaseInstrument(ABC):
    """Абстрактный интерфейс для любого источника спектра (SDR, VISA/SCPI, симулятор)."""

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def configure(self, cfg: PanoramaConfig) -> None: ...

    @abstractmethod
    def capture_spectrum(self) -> Spectrum: ...
