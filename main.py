import sys
import os

# Иконка в таскбаре Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("pemin.detector")

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
from core.app_icon import app_icon
from gui.main_window import MainWindow


def _install_desktop_entry():
    base = os.path.dirname(os.path.abspath(__file__))
    icon = os.path.join(base, "image", "icon.png")
    desktop_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
    desktop_file = os.path.join(desktop_dir, "pemin-detector.desktop")
    os.makedirs(desktop_dir, exist_ok=True)
    with open(desktop_file, "w", encoding="utf-8") as f:
        f.write(f"""[Desktop Entry]
Name=ПЭМИН Детектор
Exec=python3 {base}/main.py
Icon={icon}
Type=Application
StartupWMClass=main
Categories=Science;
""")
    os.system("update-desktop-database " + desktop_dir)


def main():
    if sys.platform == "linux":
        _install_desktop_entry()
    app = QApplication(sys.argv)
    app.setDesktopFileName("pemin-detector")
    _icon = app_icon()
    app.setWindowIcon(_icon)
    win = MainWindow()
    win.setWindowIcon(_icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
