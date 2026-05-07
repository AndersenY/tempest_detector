import sys
import os

# Добавляем Qt6/bin для корректной загрузки DLL на Windows
if sys.platform == "win32":
    import site
    for sp in site.getsitepackages():
        qt_bin = os.path.join(sp, "PyQt6", "Qt6", "bin")
        if os.path.isdir(qt_bin):
            os.add_dll_directory(qt_bin)
            break
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
