import sys
import os

# On Windows, add lib/ to the DLL search path before importing SDR backends.
# Place rtlsdr.dll, hackrf.dll, etc. in the lib/ directory.
if sys.platform == "win32":
    _lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
    if os.path.isdir(_lib_dir):
        os.add_dll_directory(_lib_dir)

from PyQt6.QtWidgets import QApplication
from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
