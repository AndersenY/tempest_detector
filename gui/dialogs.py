"""Локализованные диалоговые окна в стиле приложения."""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QDialogButtonBox, QInputDialog,
                              QMessageBox)
from PyQt6.QtCore import Qt


def _theme(parent) -> dict:
    p = parent
    while p is not None:
        if hasattr(p, '_theme'):
            return p._theme
        p = p.parent() if callable(getattr(p, 'parent', None)) else None
    from gui.theme import DARK
    return DARK


def _style(t: dict) -> str:
    return f"""
        QDialog {{
            background: {t['bg_widget']};
        }}
        QLabel#MsgText {{
            color: {t['text']};
            font-size: 13px;
            background: transparent;
        }}
        QPushButton {{
            background: {t['bg_input']};
            color: {t['text']};
            border: 1px solid {t['border_input']};
            border-radius: 4px;
            padding: 4px 14px;
            font-size: 12px;
            min-height: 24px;
            min-width: 64px;
        }}
        QPushButton:hover {{
            background: {t['border']};
        }}
        QPushButton#BtnPrimary {{
            background: {t['btn_primary_bg']};
            color: white;
            border: none;
            font-weight: 600;
        }}
        QPushButton#BtnPrimary:hover {{
            background: {t['btn_primary_hover']};
        }}
        QPushButton#BtnDanger {{
            background: {t['btn_danger']};
            color: white;
            border: none;
            font-weight: 600;
        }}
        QPushButton#BtnDanger:hover {{
            background: {t['btn_danger_hover']};
        }}
        QLineEdit, QDoubleSpinBox, QSpinBox {{
            background: {t['bg_input']};
            color: {t['text']};
            border: 1px solid {t['border_input']};
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 13px;
            min-height: 26px;
        }}
    """


class _MsgDialog(QDialog):
    """Базовый кастомный диалог в стиле приложения."""

    def __init__(self, parent, title: str, text: str, t: dict):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet(_style(t))

        root = QVBoxLayout(self)
        root.setSpacing(20)
        root.setContentsMargins(24, 20, 24, 16)

        lbl = QLabel(text)
        lbl.setObjectName("MsgText")
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        root.addWidget(lbl)

        self._btn_row = QHBoxLayout()
        self._btn_row.setSpacing(8)
        self._btn_row.addStretch()
        root.addLayout(self._btn_row)

    def _add_btn(self, label: str, object_name: str, role: str = "normal") -> QPushButton:
        btn = QPushButton(label)
        btn.setObjectName(object_name)
        self._btn_row.addWidget(btn)
        return btn


def warning(parent, title: str, text: str) -> None:
    t = _theme(parent)
    dlg = _MsgDialog(parent, title, text, t)
    ok = dlg._add_btn("ОК", "BtnPrimary")
    ok.clicked.connect(dlg.accept)
    dlg.exec()


def information(parent, title: str, text: str) -> None:
    t = _theme(parent)
    dlg = _MsgDialog(parent, title, text, t)
    ok = dlg._add_btn("ОК", "BtnPrimary")
    ok.clicked.connect(dlg.accept)
    dlg.exec()


def critical(parent, title: str, text: str) -> None:
    t = _theme(parent)
    dlg = _MsgDialog(parent, title, text, t)
    ok = dlg._add_btn("ОК", "BtnPrimary")
    ok.clicked.connect(dlg.accept)
    dlg.exec()


def question(parent, title: str, text: str) -> bool:
    """Возвращает True если нажали «Да». Порядок кнопок: Нет | Да."""
    t = _theme(parent)
    dlg = _MsgDialog(parent, title, text, t)
    yes = dlg._add_btn("Да",  "BtnPrimary")
    no  = dlg._add_btn("Нет", "BtnDanger")
    no.clicked.connect(dlg.reject)
    yes.clicked.connect(dlg.accept)
    return dlg.exec() == QDialog.DialogCode.Accepted


def get_double(parent, title: str, label: str, value: float,
               min_val: float, max_val: float, decimals: int = 1):
    """QInputDialog с русскими кнопками и темой приложения."""
    t = _theme(parent)
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setDoubleValue(value)
    dlg.setDoubleMinimum(min_val)
    dlg.setDoubleMaximum(max_val)
    dlg.setDoubleDecimals(decimals)
    dlg.setStyleSheet(_style(t))
    bb = dlg.findChild(QDialogButtonBox)
    if bb:
        for btn in bb.buttons():
            role = bb.buttonRole(btn)
            if role == QDialogButtonBox.ButtonRole.AcceptRole:
                btn.setText("ОК")
                btn.setObjectName("BtnPrimary")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            elif role == QDialogButtonBox.ButtonRole.RejectRole:
                btn.setText("Отмена")
    ok = bool(dlg.exec())
    return dlg.doubleValue(), ok
