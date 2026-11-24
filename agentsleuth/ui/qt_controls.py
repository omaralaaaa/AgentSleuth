"""Control measurements shared by the Qt windows."""

from PySide6.QtWidgets import QPushButton


BUTTON_WIDTHS = {
    'Scan for artifacts…': 159, 'Browse': 103, 'Change folder': 117,
    'Close tab': 103, 'Clear': 103, 'Open export folder': 152, 'Uploads by prompt': 145,
    'Scan this PC': 110, 'Scan evidence folder…': 173, 'Select all': 131,
    'Open selected': 117, 'Show file in folder': 159, 'Close': 103,
}


def make_button(text, action, *, accent=False):
    button = QPushButton(text)
    button.setFixedSize(BUTTON_WIDTHS[text], 31)
    button.setProperty('accent', accent)
    button.clicked.connect(action)
    return button
