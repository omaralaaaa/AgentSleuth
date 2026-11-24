"""Qt discovery and prompt upload dialogs."""

from pathlib import Path
from queue import Empty
from threading import Event

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from agentsleuth.core.discovery import live_roots, scan
from agentsleuth.core.upload_listing import prompt_uploads
from agentsleuth.core.utils import short
from agentsleuth.ui.worker import AgentWorker
from .qt_controls import make_button


def tree_widget(labels, widths):
    tree = QTreeWidget()
    tree.setHeaderLabels(labels)
    tree.setUniformRowHeights(True)
    tree.setAlternatingRowColors(True)
    for index, width in enumerate(widths):
        tree.header().setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
        tree.setColumnWidth(index, width)
    tree.header().setStretchLastSection(False)
    return tree


class ScanDialog(QDialog):
    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.setWindowTitle('Discover agent evidence')
        self.resize(930, 480)
        self.setMinimumSize(530, 300)
        self.worker = AgentWorker('Qt discovery')
        self.poll = QTimer(self, interval=80)
        self.poll.timeout.connect(self._poll)
        self.root_path = None
        self.cancel_scan = Event()
        self.findings = []
        self.ready = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(6)
        actions = QHBoxLayout()
        local = make_button('Scan this PC', lambda: self.start(None))
        actions.addWidget(local)
        offline = make_button('Scan evidence folder…', self.choose)
        actions.addWidget(offline)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel('Scan known locations on this PC or select an extracted evidence folder.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = tree_widget(['Select', 'Agent', 'Evidence folder', 'Source'], [64, 125, 500, 210])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.table.itemClicked.connect(self._click)
        self.table.itemDoubleClicked.connect(self._double_click)
        self.table.itemChanged.connect(self._update_buttons)
        layout.addWidget(self.table, 1)
        footer = QHBoxLayout()
        footer.addStretch()
        self.select_all = make_button('Select all', self._toggle_all)
        self.open_button = make_button('Open selected', self.open_selected, accent=True)
        footer.addWidget(self.select_all)
        footer.addWidget(self.open_button)
        layout.addLayout(footer)
        for key, action in (('Ctrl+A', self._check_all), ('Return', self.open_selected),
                            ('Enter', self.open_selected), ('Space', self._toggle_current)):
            shortcut = QShortcut(QKeySequence(key), self.table)
            shortcut.activated.connect(action)
        self._update_buttons()

    def choose(self):
        directory = QFileDialog.getExistingDirectory(self, 'Select an extracted C: drive or collection folder')
        if directory:
            self.start(Path(directory).resolve())

    def start(self, root):
        self.cancel_scan.set()
        cancelled = self.cancel_scan = Event()
        self.root_path = root
        self.findings = []
        self.ready = []
        self.table.clear()
        self._update_buttons()
        self.status.setText(f'Scanning {root or "known agent locations on this PC"}…')

        def discover(progress):
            return scan([root] if root else live_roots(), cancelled,
                        lambda dirs, hits: progress(f'{dirs:,} directories scanned · {hits:,} agent folders'),
                        known_locations=root is None)

        self.worker.start('scanned', discover)
        self.poll.start()

    def _poll(self):
        while True:
            try:
                request, kind, value = self.worker.results.get_nowait()
            except Empty:
                return
            if request != self.worker.request:
                continue
            if kind == 'progress':
                self.status.setText(value)
            elif kind == 'error':
                self.status.setText(f'Scan failed · {value}')
                self.poll.stop()
            else:
                self._show_results(*value)
                self.poll.stop()

    def _show_results(self, findings, skipped):
        self.findings = findings
        for index, hit in enumerate(findings):
            item = QTreeWidgetItem(['', hit.agent, str(hit.path), hit.status])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            if hit.source is not None:
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                self.ready.append(item)
            self.table.addTopLevelItem(item)
        self.status.setText(f'Complete · {len(findings):,} agent folders · {skipped:,} inaccessible directories')
        self._update_buttons()

    def _toggle(self, item):
        if item in self.ready:
            item.setCheckState(0, Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked
                               else Qt.CheckState.Checked)

    def _click(self, item, _column):
        self._toggle(item)

    def _toggle_current(self):
        self._toggle(self.table.currentItem())

    def _double_click(self, item, column):
        if column != 0 and item in self.ready:
            self._open([item])

    def _selected(self):
        return [item for item in self.ready if item.checkState(0) == Qt.CheckState.Checked]

    def _update_buttons(self):
        selected = self._selected()
        active = {id(item) for item in selected}
        for item in self.ready:
            item.setSelected(id(item) in active)
        count = len(selected)
        self.select_all.setEnabled(bool(self.ready))
        self.select_all.setText('Clear selection' if self.ready and count == len(self.ready) else 'Select all')
        self.open_button.setEnabled(bool(count))

    def _set_all(self, state):
        self.table.blockSignals(True)
        for item in self.ready:
            item.setCheckState(0, state)
        self.table.blockSignals(False)
        self._update_buttons()

    def _check_all(self):
        self._set_all(Qt.CheckState.Checked)

    def _toggle_all(self):
        self._set_all(Qt.CheckState.Unchecked if len(self._selected()) == len(self.ready) else Qt.CheckState.Checked)

    def open_selected(self):
        self._open(self._selected())

    def _open(self, rows):
        hits = [self.findings[item.data(0, Qt.ItemDataRole.UserRole)] for item in rows]
        if hits and self.viewer.open_evidence_sources(hits, self.root_path):
            self.accept()

    def done(self, result):
        self.cancel_scan.set()
        self.poll.stop()
        self.worker.close()
        super().done(result)


class UploadDialog(QDialog):
    def __init__(self, pane, directory):
        super().__init__(pane)
        self.setWindowTitle('Uploads by prompt')
        self.resize(880, 520)
        self.setMinimumSize(530, 350)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.tree = tree_widget(['Prompt / uploaded file', 'Status', 'Exported filename'], [450, 110, 265])
        layout.addWidget(self.tree, 1)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFixedHeight(110)
        layout.addWidget(self.text)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 15, 0)
        layout.addLayout(footer)
        self.show_file = make_button('Show file in folder', lambda: self._reveal(pane))
        self.show_file.setEnabled(False)
        footer.addWidget(self.show_file)
        footer.addStretch()
        close = make_button('Close', self.reject)
        footer.addWidget(close)
        self.tree.currentItemChanged.connect(self._select)
        self.tree.itemDoubleClicked.connect(lambda *_: self._reveal(pane))
        for turn, ordinal, prompt, files in prompt_uploads(pane.result, directory):
            item = QTreeWidgetItem([f'Turn {turn} · #{ordinal} · {short(" ".join(prompt.split()), 120)}'])
            item.setData(0, Qt.ItemDataRole.UserRole, prompt)
            self.tree.addTopLevelItem(item)
            for name, target, status in files:
                child = QTreeWidgetItem([name, status, target.name if target else ''])
                if target:
                    child.setData(0, Qt.ItemDataRole.UserRole, str(target))
                item.addChild(child)
            item.setExpanded(True)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self.text.setPlainText('No uploaded files are linked to prompts in this conversation.')

    def _select(self, current, _previous):
        parent = current.parent() if current else None
        self.text.setPlainText((parent or current).data(0, Qt.ItemDataRole.UserRole) if current else '')
        self.show_file.setEnabled(bool(parent and current.data(0, Qt.ItemDataRole.UserRole)))

    def _reveal(self, pane):
        item = self.tree.currentItem()
        if item and item.parent() and (path := item.data(0, Qt.ItemDataRole.UserRole)):
            pane.window().reveal(Path(path))
