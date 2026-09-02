"""Оформление окна: обычный тёмный вид и ночной режим.

Ночной режим — рабочий инструмент, а не украшение. Светящийся белым экран
посреди тёмного двора сбивает адаптацию глаза на двадцать минут, после чего
слабые объекты просто перестают быть видны. Поэтому в нём остаются только
тусклые красные тона, а яркость всего окна снижается.
"""
from __future__ import annotations

BASE = """
QWidget { background: #0d1119; color: #d8dfec; font-size: 13px; }
QGroupBox {
  border: 1px solid #22304a; border-radius: 6px; margin-top: 14px;
  padding: 10px 8px 8px 8px;
}
QGroupBox::title {
  subcontrol-origin: margin; left: 10px; padding: 0 4px;
  color: #7f8fab;
}
QLabel#panelTitle { font-size: 12px; font-weight: 700; color: #7f9ac4;
                    letter-spacing: 1px; }
QLabel#muted { color: #7c879c; font-size: 12px; }
QLabel#clock { font-size: 17px; font-weight: 600; color: #e8eefb; }
QPushButton {
  background: #182236; border: 1px solid #2b3c5c; border-radius: 5px;
  padding: 6px 10px;
}
QPushButton:hover { background: #21304a; }
QPushButton:disabled { color: #56607a; background: #131a28; }
QPushButton#primary {
  background: #24446e; border-color: #3d6ea8; font-weight: 600; padding: 9px;
}
QPushButton#primary:hover { background: #2c548a; }
QPushButton#night { background: #3a1712; border-color: #6b2a20; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextBrowser,
QListWidget, QTableWidget {
  background: #121a28; border: 1px solid #263450; border-radius: 4px;
  padding: 4px; selection-background-color: #2d4f80;
}
QListWidget::item { padding: 5px 4px; }
QListWidget::item:selected { background: #244063; }
QSlider::groove:horizontal { height: 5px; background: #22304a; border-radius: 3px; }
QSlider::handle:horizontal {
  width: 15px; margin: -6px 0; border-radius: 8px; background: #6f9bd6;
}
QHeaderView::section { background: #182236; border: 0; padding: 4px; }
QStatusBar { color: #7c879c; }
QSplitter::handle { background: #1a2436; }
"""

NIGHT = """
QWidget { background: #050202; color: #a03428; font-size: 13px; }
QGroupBox { border: 1px solid #3a1310; }
QGroupBox::title, QLabel#panelTitle, QLabel#muted { color: #7c281f; }
QLabel#clock { color: #c04030; }
QPushButton {
  background: #1a0806; border: 1px solid #4a1a14; color: #a03428;
}
QPushButton:hover { background: #250b08; }
QPushButton:disabled { color: #4a1a14; }
QPushButton#primary { background: #33100c; border-color: #6b2a20; }
QPushButton#night { background: #4a1a14; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextBrowser,
QListWidget, QTableWidget {
  background: #0a0303; border: 1px solid #3a1310; color: #a03428;
  selection-background-color: #4a1a14;
}
QListWidget::item:selected { background: #3a1310; }
QSlider::groove:horizontal { background: #3a1310; }
QSlider::handle:horizontal { background: #8b2f24; }
QHeaderView::section { background: #1a0806; }
QSplitter::handle { background: #1a0806; }
"""


def stylesheet(night: bool) -> str:
    return BASE + (NIGHT if night else "")
