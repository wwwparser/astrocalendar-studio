"""Оформление интерфейса.

Приложение рабочее, а не витринное: спокойные цвета, плотные списки, никакой
декоративности. Две темы — светлая и тёмная, обе строятся из одного набора
токенов, чтобы не расходились.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tokens:
    window: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    selection: str
    must: str
    interesting: str
    optional: str
    technical: str
    ok: str
    warn: str
    review: str


DARK = Tokens(
    window="#171b22", surface="#1e232c", surface_alt="#242a35", border="#333b48",
    text="#e6ebf2", muted="#8d99ab", accent="#3d8bfd", accent_text="#ffffff",
    selection="#2c4770", must="#ffcc66", interesting="#8fd3ff",
    optional="#9aa7b8", technical="#6d7787", ok="#69d18b", warn="#ffb347",
    review="#ff7a7a",
)

LIGHT = Tokens(
    window="#f4f6f9", surface="#ffffff", surface_alt="#eef2f7", border="#d3dae4",
    text="#1a212b", muted="#5f6b7c", accent="#1f6feb", accent_text="#ffffff",
    selection="#cfe2ff", must="#a56a00", interesting="#0b6a95",
    optional="#5f6b7c", technical="#8a94a3", ok="#1e7a44", warn="#a56a00",
    review="#b02a2a",
)


def tokens(theme: str) -> Tokens:
    return LIGHT if theme == "light" else DARK


def stylesheet(theme: str = "dark") -> str:
    t = tokens(theme)
    return f"""
    QWidget {{
        background: {t.window};
        color: {t.text};
        font-size: 13px;
    }}
    QMainWindow::separator {{ background: {t.border}; width: 1px; height: 1px; }}
    QGroupBox {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: 6px;
        margin-top: 14px;
        padding: 8px 8px 8px 8px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {t.muted};
    }}
    QLabel#Heading {{ font-size: 15px; font-weight: 600; }}
    QLabel#Muted {{ color: {t.muted}; }}
    QLabel#Status {{ color: {t.muted}; padding: 2px 6px; }}
    QPushButton {{
        background: {t.surface_alt};
        border: 1px solid {t.border};
        border-radius: 5px;
        padding: 6px 12px;
    }}
    QPushButton:hover {{ background: {t.selection}; }}
    QPushButton:disabled {{ color: {t.muted}; background: {t.surface}; }}
    QPushButton#Primary {{
        background: {t.accent}; color: {t.accent_text};
        border: 1px solid {t.accent}; font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: {t.accent}; }}
    QLineEdit, QComboBox, QSpinBox, QDateTimeEdit, QPlainTextEdit, QTextEdit {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: 5px;
        padding: 4px 6px;
        selection-background-color: {t.selection};
    }}
    QTreeView, QTableView, QListWidget {{
        background: {t.surface};
        alternate-background-color: {t.surface_alt};
        border: 1px solid {t.border};
        border-radius: 6px;
        gridline-color: {t.border};
        selection-background-color: {t.selection};
        selection-color: {t.text};
    }}
    QHeaderView::section {{
        background: {t.surface_alt};
        color: {t.muted};
        border: none;
        border-right: 1px solid {t.border};
        border-bottom: 1px solid {t.border};
        padding: 5px 4px;
        font-weight: 600;
    }}
    QTabWidget::pane {{
        border: 1px solid {t.border}; border-radius: 6px; top: -1px;
        background: {t.surface};
    }}
    QTabBar::tab {{
        background: transparent; color: {t.muted};
        padding: 7px 14px; border: 1px solid transparent;
        border-top-left-radius: 6px; border-top-right-radius: 6px;
    }}
    QTabBar::tab:selected {{
        background: {t.surface}; color: {t.text};
        border-color: {t.border}; border-bottom-color: {t.surface};
    }}
    QScrollArea {{ border: none; }}
    QSplitter::handle {{ background: {t.border}; }}
    QProgressBar {{
        border: 1px solid {t.border}; border-radius: 5px;
        background: {t.surface}; text-align: center; height: 16px;
    }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 4px; }}
    QCheckBox, QRadioButton {{ spacing: 7px; padding: 1px 0; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 14px; height: 14px;
        border: 1px solid {t.border};
        background: {t.surface};
    }}
    QCheckBox::indicator {{ border-radius: 3px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: {t.accent};
    }}
    QCheckBox::indicator:checked {{
        background: {t.accent}; border-color: {t.accent};
        image: none;
    }}
    QRadioButton::indicator:checked {{
        background: {t.accent}; border: 4px solid {t.surface};
        outline: 1px solid {t.accent};
    }}
    QTreeWidget::item, QTableView::item {{ padding: 2px 4px; }}
    QToolTip {{
        background: {t.surface_alt}; color: {t.text};
        border: 1px solid {t.border}; padding: 4px;
    }}
    """


RANK_COLORS = {
    "must": lambda t: t.must,
    "interesting": lambda t: t.interesting,
    "optional": lambda t: t.optional,
    "technical": lambda t: t.technical,
}

QA_COLORS = {
    "OK": lambda t: t.ok,
    "WARN": lambda t: t.warn,
    "REVIEW": lambda t: t.review,
}
