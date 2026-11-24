"""Transcript cards mounted only near the Qt viewport."""

from bisect import bisect_right
from itertools import accumulate
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractScrollArea, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from agentsleuth.core.upload_listing import attachment_links
from agentsleuth.core.utils import safe_text
from agentsleuth.ui.card_content import CardContentMixin, card_heading
from agentsleuth.ui.powershell import COLORS


def evidence_label(text, color='#dee1e5', points=9, bold=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setFont(QFont('Consolas', points, QFont.Weight.Bold if bold else QFont.Weight.Normal))
    widget.setStyleSheet(f'color: {color}; background: transparent;')
    return widget


class Guide(QFrame):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(10, 0, 2, self.height(), QColor('#566677'))
        painter.fillRect(11, 17, 13, 2, QColor('#566677'))


class EvidenceText(QPlainTextEdit):
    def __init__(self, text, bg, width, max_rows, monospace, parts=None):
        super().__init__()
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFont(QFont('Consolas' if monospace else 'Segoe UI', 10))
        self.setStyleSheet(f'QPlainTextEdit {{ background: {bg}; border: 0; }}')
        self.document().setDocumentMargin(2)
        metrics = QFontMetrics(self.font())
        line_height = metrics.lineSpacing()
        measured = metrics.boundingRect(0, 0, max(80, width - 28), 32767,
                                        Qt.TextFlag.TextWordWrap.value, text[:8192]).height()
        self.setFixedHeight(min(max_rows * line_height, max(line_height, measured)) + 5)
        if not parts:
            self.setPlainText(text)
            return
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        for value, tags in zip(parts[::2], parts[1::2]):
            style = QTextCharFormat()
            if tags:
                style.setForeground(QColor(COLORS[tags[0]]))
            cursor.insertText(value, style)
        cursor.endEditBlock()

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if (delta >= 0 and bar.value() == bar.minimum()) or (delta < 0 and bar.value() == bar.maximum()):
            event.ignore()
        else:
            super().wheelEvent(event)


class Card(QFrame, CardContentMixin):
    def __init__(self, pane, entry, width, parts):
        super().__init__(pane.transcript.viewport())
        self.pane = pane
        self.result = pane.result
        self._command_styles = {id(entry): parts} if parts else {}
        user = entry.get('role') == 'user' and entry['kind'] == 'message'
        self.bg = '#28313b' if user else '#23262b' if entry['kind'] == 'message' else '#25282d'
        self.spans = QHBoxLayout(self)
        self.spans.setContentsMargins(16, 8 if user else 3, 16, 0)
        self.spans.setSpacing(0)
        nested = id(entry) in pane.index.prompt_for
        if nested:
            guide = Guide()
            guide.setFixedWidth(24)
            self.spans.addWidget(guide)
        content = QFrame()
        content.setObjectName('entryCard')
        content.setStyleSheet(f'QFrame#entryCard {{ background: {self.bg}; '
                              f'border: {int(user)}px solid #454a53; }}')
        self.spans.addWidget(content, 1)
        self.width_hint = width - 32 - 24 * nested
        shell = QVBoxLayout(content)
        shell.setContentsMargins(8, 11, 13, 4)
        shell.setSpacing(0)
        card = QVBoxLayout()
        card.setContentsMargins(5, 0, 0, 0)
        card.setSpacing(0)
        shell.addLayout(card)
        header = QHBoxLayout()
        label, meta = card_heading(entry, pane.provider.name)
        heading = evidence_label(label, '#99b5d3' if entry['kind'] == 'message' else '#adb3bc', 10, True)
        heading.setMinimumHeight(21)
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(evidence_label(meta, '#adb3bc', 8))
        card.addLayout(header)
        card.addSpacing(2)
        self._populate_card(card, entry, self.bg)
        count = pane.index.response_counts.get(id(entry), 0)
        if user and count:
            marker = '▸' if id(entry) in pane.collapsed else '▾'
            button = QPushButton(f'{marker}  {count} {"response" if count == 1 else "responses"}')
            button.setProperty('disclosure', True)
            button.setFixedSize(max(103, len(button.text()) * 7 + 12), 23)
            button.clicked.connect(lambda: pane.toggle_prompt(id(entry)))
            shell.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)

    def _body(self, panel, content, bg, max_rows=12, monospace=False, command_styles=None):
        value = safe_text(content).encode('utf-8', errors='backslashreplace').decode('utf-8')
        panel.addSpacing(3)
        panel.addWidget(EvidenceText(value, bg, self.width_hint, max_rows, monospace, command_styles))
        panel.addSpacing(10)

    def _field(self, panel, label, value, multiline=False, command_styles=None, show_empty=False):
        if value is None or (value == '' and not show_empty):
            return
        if multiline:
            panel.addSpacing(7)
            panel.addWidget(evidence_label(label, '#adb3bc', bold=True))
            self._body(panel, value, self.bg, 9, True, command_styles)
        else:
            widget = evidence_label(f'{label}:  {value}')
            widget.setWordWrap(True)
            panel.addSpacing(4)
            panel.addWidget(widget)
            panel.addSpacing(3)

    def _card_permissions(self, panel, permission):
        panel.addSpacing(2)
        panel.addWidget(evidence_label(f'Permissions: {permission}', '#adb3bc'))
        panel.addSpacing(4)

    def _filename_link(self, panel, filename, target=None, suffix=''):
        label = f'{filename}  {suffix}'.rstrip()
        panel.addSpacing(4)
        if target and Path(target).is_file():
            button = QPushButton(label)
            button.setProperty('fileLink', True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda: self.pane.window().reveal(Path(target)))
            panel.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
        else:
            panel.addWidget(evidence_label(label))
        panel.addSpacing(3)

    def _file_links(self, panel, file_refs, attachments):
        directory = (self.result or {}).get('output_directory')
        for link in attachment_links(file_refs or (), attachments, directory):
            target = link.get('saved_path')
            self._filename_link(panel, link['filename'], target,
                                '· extracted copy' if target and Path(target).is_file() else '')


class Transcript(QAbstractScrollArea):
    def __init__(self, pane):
        super().__init__()
        self.pane = pane
        self.rows = []
        self.live = {}
        self.sizes = {}
        self.styles = {}
        self.offsets = [0]
        self.layout_width = 0
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.refresh = QTimer(self, interval=0, singleShot=True)
        self.refresh.timeout.connect(self._mount)
        self.verticalScrollBar().valueChanged.connect(lambda _: self.refresh.start())

    def replace(self, rows, styles=None, *, reset=False, keep_position=False):
        bar = self.verticalScrollBar()
        current = bar.value()
        anchor = self._at(current) if self.rows and keep_position else None
        anchor_key = self.rows[anchor][0] if anchor is not None else None
        inset = current - self.offsets[anchor] if anchor is not None else 0
        for widget in self.live.values():
            widget.hide()
            widget.deleteLater()
        self.live.clear()
        if reset:
            self.sizes.clear()
        self.styles = styles or {}
        self.rows = rows
        self._measure()
        new_anchor = next((i for i, (key, _) in enumerate(rows) if key == anchor_key), None)
        bar.setValue(self.offsets[new_anchor] + inset if new_anchor is not None else 0)
        self._mount()

    def _measure(self):
        self.offsets = list(accumulate((
            self.sizes.get(key, 44 if isinstance(entry, str) else 84)
            for key, entry in self.rows), initial=0))
        bar = self.verticalScrollBar()
        bar.setPageStep(self.viewport().height())
        bar.setSingleStep(24)
        bar.setRange(0, max(0, self.offsets[-1] - self.viewport().height()))

    def _at(self, pixel):
        return min(len(self.rows) - 1, bisect_right(self.offsets, max(0, pixel)) - 1)

    def _mount(self):
        if not self.rows:
            return
        bar = self.verticalScrollBar()
        top = bar.value()
        width = max(200, self.viewport().width())
        anchor = self._at(top)
        offset = top - self.offsets[anchor]
        at_end = top > 0 and top == bar.maximum()
        desired = set(range(self._at(top - 160), self._at(top + self.viewport().height() + 160) + 1))
        for row in self.live.keys() - desired:
            widget = self.live.pop(row)
            widget.hide()
            widget.deleteLater()
        changed = False
        for row in sorted(desired):
            key, entry = self.rows[row]
            if row not in self.live:
                if isinstance(entry, str):
                    widget = evidence_label(entry, '#adb3bc', 10, True)
                    widget.setContentsMargins(18, 10, 18, 2)
                    widget.setParent(self.viewport())
                else:
                    widget = Card(self.pane, entry, width, self.styles.get(key))
                self.live[row] = widget
                layout = widget.layout()
                preferred = layout.totalHeightForWidth(width) if layout and layout.hasHeightForWidth() else -1
                height = max(44 if isinstance(entry, str) else 35,
                             preferred if preferred >= 0 else widget.sizeHint().height())
                changed |= self.sizes.get(key) != height
                self.sizes[key] = height
        if changed:
            self._measure()
            bar.setValue(bar.maximum() if at_end else self.offsets[anchor] + offset)
            self.refresh.start()
        for row, widget in self.live.items():
            widget.setGeometry(0, self.offsets[row] - bar.value(), width, self.sizes[self.rows[row][0]])
            widget.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.viewport().width()
        if self.rows and width != self.layout_width:
            self.layout_width = width
            self.replace(self.rows, self.styles, reset=True, keep_position=True)
        else:
            self._measure()
            self.refresh.start()
