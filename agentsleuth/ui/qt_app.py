"""Qt desktop application."""

import argparse
import os
from pathlib import Path
from queue import Empty
import subprocess
import sys
from threading import Event
from time import perf_counter, sleep

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit,
    QMainWindow, QProgressBar, QSplitter, QTabWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from agentsleuth.core.export import (
    preference_path, read_export_root, save_export_root, validate_export_root,
)
from agentsleuth.core.search import ALL_ENTRIES, TranscriptIndex
from agentsleuth.core.upload_listing import export_folder
from agentsleuth.core.utils import short
from agentsleuth.parsers import antigravity, claude, codex, opencode
from agentsleuth.ui.render_plan import build_plan
from agentsleuth.ui.windows_explorer import reveal_file
from agentsleuth.ui.worker import AgentWorker, load_threads, reconstruct
from .qt_dialogs import ScanDialog, UploadDialog, tree_widget
from .qt_controls import make_button
from .qt_transcript import Transcript, evidence_label


PROVIDERS = (codex, opencode, claude, antigravity)
THEME = """
QWidget { background: #191b1f; color: #dee1e5; }
QFrame#panel { background: #23262b; }
QLineEdit, QTreeWidget, QPlainTextEdit {
    background: #191b1f; border: 1px solid #454a53; selection-background-color: #99b5d3;
    selection-color: #191b1f;
}
QLineEdit, QComboBox { padding: 5px; }
QPushButton, QComboBox, QHeaderView::section {
    background: #23262b; border: 1px solid #454a53; color: #dee1e5;
}
QPushButton { padding: 5px 10px; }
QPushButton:hover { background: #343a42; }
QPushButton:focus { border-color: #99b5d3; }
QPushButton:disabled { color: #adb3bc; }
QPushButton[accent="true"], QTabBar::tab:selected { background: #99b5d3; color: #191b1f; }
QPushButton[disclosure="true"], QPushButton[fileLink="true"] {
    background: transparent; border: 1px solid transparent; color: #99b5d3; text-align: left;
}
QPushButton[fileLink="true"] { text-decoration: underline; padding: 1px 3px; }
QPushButton[disclosure="true"] { padding: 3px 5px; }
QPushButton[disclosure="true"]:hover, QPushButton[fileLink="true"]:hover { background: #343a42; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 5px 13px; background: #23262b; border: 1px solid #454a53; }
QTreeWidget { background: #23262b; alternate-background-color: #282b30; }
QTreeWidget::item { min-height: 29px; }
QHeaderView::section { padding: 6px; color: #adb3bc; }
QSplitter::handle { background: #454a53; }
"""


def add_button(layout, text, action, accent=False):
    button = make_button(text, action, accent=accent)
    layout.addWidget(button)
    return button


class AgentPane(QFrame):
    def __init__(self, viewer, provider, closable=False):
        super().__init__()
        self.viewer = viewer
        self.provider = provider
        self.worker = AgentWorker(provider.name)
        self.render_worker = AgentWorker(f'{provider.name}-render')
        self.render_cancel = Event()
        self.scan_source = None
        self.source = None
        self.loading = False
        self.threads = []
        self.active_thread = None
        self.cache = {}
        self.result = self.index = None
        self.retained_kind = ALL_ENTRIES
        self.collapsed = set()
        self.upload_dialog = None
        self.sidebar_columns = getattr(provider, 'sidebar_columns', ())
        self.build(closable)
        self.timer = QTimer(self, interval=30)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def build(self, closable):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 6, 2, 2)
        layout.setSpacing(3)
        top = QVBoxLayout()
        top.setContentsMargins(15, 19, 15, 16)
        top.setSpacing(8)
        layout.addLayout(top)
        row = QHBoxLayout()
        top.addLayout(row)
        source_label = evidence_label(self.provider.source_label, '#adb3bc', 10)
        source_label.setFixedWidth(round(len(self.provider.source_label) * 7.4) + 3)
        row.addWidget(source_label)
        self.path = QLineEdit()
        self.path.setFixedHeight(29)
        self.path.returnPressed.connect(self.load_source)
        row.addWidget(self.path, 1)
        add_button(row, 'Browse', self.browse_source)
        if closable:
            add_button(row, 'Close tab', lambda: self.viewer.close_source_tab(self))

        row = QHBoxLayout()
        top.addLayout(row)
        export_label = evidence_label('Export directory:', '#adb3bc', 10)
        export_label.setFixedWidth(129)
        row.addWidget(export_label)
        self.export_path = QLineEdit(str(self.viewer.export_root or ''))
        self.export_path.setFixedHeight(29)
        self.export_path.setReadOnly(True)
        row.addWidget(self.export_path, 1)
        add_button(row, 'Change folder', self.viewer.change_export_folder)
        status_row = QHBoxLayout()
        top.addLayout(status_row)
        self.status = evidence_label(self.provider.source_hint, '#adb3bc', 10)
        status_row.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        status_row.addWidget(self.progress)
        self.progress.hide()

        body = QHBoxLayout()
        body.setContentsMargins(12, 0, 12, 12)
        layout.addLayout(body, 1)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(5)
        body.addWidget(split)
        left = QFrame()
        left.setObjectName('panel')
        left.setMinimumWidth(205)
        sidebar = QVBoxLayout(left)
        sidebar.setContentsMargins(11, 12, 11, 12)
        sidebar.setSpacing(6)
        heading = evidence_label('CONVERSATION INDEX', '#adb3bc', 12, True)
        heading.setFixedHeight(23)
        sidebar.addWidget(heading)
        filter_label = evidence_label('Filter conversations', '#adb3bc', 10)
        filter_label.setFixedHeight(21)
        sidebar.addWidget(filter_label)
        self.sidebar_filter = QLineEdit()
        self.sidebar_filter.setFixedHeight(29)
        self.sidebar_filter.textChanged.connect(self.populate_sidebar)
        sidebar.addWidget(self.sidebar_filter)
        sidebar.addSpacing(4)
        self.sessions = tree_widget(['#', 'Conversation', *(x[1] for x in self.sidebar_columns)],
                                    [42, 225, *(x[2] for x in self.sidebar_columns)])
        self.sessions.setRootIsDecorated(False)
        self.sessions.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.sessions.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.sessions.currentItemChanged.connect(self.open_selected_thread)
        sidebar.addWidget(self.sessions, 1)
        empty = 'No source selected' if self.sidebar_columns else 'No database selected'
        self.sidebar_info = evidence_label(getattr(self.provider, 'sidebar_empty_text', empty), '#adb3bc')
        sidebar.addWidget(self.sidebar_info)
        split.addWidget(left)

        right = QFrame()
        right.setMinimumWidth(480)
        view = QVBoxLayout(right)
        view.setContentsMargins(0, 0, 0, 0)
        view.setSpacing(0)
        header = QVBoxLayout()
        header.setContentsMargins(15, 10, 15, 10)
        header.setSpacing(2)
        view.addLayout(header)
        self.thread_title = evidence_label('Select a conversation', points=15, bold=True)
        self.thread_cwd = evidence_label('', '#adb3bc')
        self.thread_source = evidence_label('', '#adb3bc')
        for label, height in ((self.thread_title, 29), (self.thread_cwd, 20), (self.thread_source, 20)):
            label.setMinimumHeight(height)
            label.setWordWrap(True)
            header.addWidget(label)
        self.export_actions = QFrame()
        exports = QHBoxLayout(self.export_actions)
        exports.setContentsMargins(0, 4, 0, 0)
        exports.setSpacing(0)
        export_notice = evidence_label('Exported files available', '#99b5d3', 10)
        export_notice.setFixedWidth(174)
        exports.addWidget(export_notice)
        exports.addSpacing(8)
        add_button(exports, 'Open export folder', self.open_export_folder)
        exports.addSpacing(4)
        add_button(exports, 'Uploads by prompt', self.show_uploads)
        exports.addStretch()
        header.addWidget(self.export_actions)
        self.export_actions.hide()

        turn_row = QHBoxLayout()
        turn_row.setContentsMargins(15, 4, 15, 4)
        view.addLayout(turn_row)
        turn_label = evidence_label('Turn:', '#adb3bc', 10)
        turn_label.setFixedWidth(43)
        turn_row.addWidget(turn_label)
        self.turn = QComboBox()
        self.turn.setFixedHeight(29)
        self.turn.addItem('Entire conversation')
        self.turn.currentIndexChanged.connect(self.turn_changed)
        turn_row.addWidget(self.turn, 1)
        self.stats = evidence_label('', '#adb3bc')
        turn_row.addWidget(self.stats)

        filters = QHBoxLayout()
        filters.setContentsMargins(15, 0, 15, 5)
        view.addLayout(filters)
        search_label = evidence_label('Search:', '#adb3bc', 10)
        search_label.setFixedWidth(55)
        filters.addWidget(search_label)
        self.search = QLineEdit()
        self.search.setFixedHeight(29)
        filters.addWidget(self.search, 1)
        self.kind = QComboBox()
        self.kind.setFixedSize(179, 29)
        self.kind.addItem(ALL_ENTRIES)
        filters.addWidget(self.kind)
        add_button(filters, 'Clear', self.clear_filters)
        self.debounce = QTimer(self, interval=120, singleShot=True)
        self.debounce.timeout.connect(self.render)
        self.search.textChanged.connect(lambda _: self.debounce.start())
        self.kind.currentIndexChanged.connect(lambda _: self.debounce.start())
        self.transcript = Transcript(self)
        view.addWidget(self.transcript, 1)
        split.addWidget(right)
        split.setSizes([325, 1000])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

    def browse_source(self):
        formats = ';;'.join(f'{label} ({pattern})' for label, pattern in self.provider.filetypes)
        path, _ = QFileDialog.getOpenFileName(self, self.provider.source_hint, filter=formats)
        if path:
            self.path.setText(path)
            self.load_source()

    def load_source(self):
        if not (value := self.path.text().strip().strip('"')):
            self.status.setText(self.provider.source_hint)
            return
        self.loading = True
        self.progress.show()
        self.status.setText(f'Reading {self.provider.name} conversations…')
        self.worker.start('loaded', load_threads, self.provider, Path(value))

    def _poll(self):
        for worker in (self.worker, self.render_worker):
            while True:
                try:
                    request, kind, value = worker.results.get_nowait()
                except Empty:
                    break
                if request != worker.request:
                    continue
                if kind == 'progress':
                    self.status.setText(value)
                elif kind == 'loaded':
                    self.loading = False
                    self.progress.hide()
                    self.source, self.threads = value
                    if self.scan_source and self.scan_source[0] == self.source and self.scan_source[1] is not None:
                        for thread in self.threads:
                            thread['_evidence_root'] = self.scan_source[1]
                    self.active_thread = None
                    self.cache.clear()
                    self.reset_conversation()
                    self.thread_title.setText('Select a conversation')
                    self.thread_cwd.clear()
                    self.thread_source.clear()
                    self.populate_sidebar()
                    status = f'Loaded {len(self.threads)} conversations'
                    self.status.setText(status + (' · select one to view' if self.threads else ''))
                elif kind == 'reconstructed':
                    self.progress.hide()
                    self.cache[self.active_thread] = value
                    self.display_result(value)
                elif kind == 'rendered':
                    self.apply_render(value)
                elif kind == 'error':
                    self.loading = False
                    self.progress.hide()
                    self.status.setText(f'Error reading {self.provider.name} evidence · {value}')
                    if self.result is None:
                        self.transcript.replace([('error', value)])

    def populate_sidebar(self):
        needle = self.sidebar_filter.text().strip().casefold()
        selected = None
        self.sessions.blockSignals(True)
        self.sessions.clear()
        count = 0
        for i, thread in enumerate(self.threads):
            searchable = ' '.join(str(thread.get(k) or '') for k in ('name', 'cwd', 'id'))
            if needle not in searchable.casefold():
                continue
            count += 1
            item = QTreeWidgetItem([f'{count:03d}', thread['name'],
                                    *(str(thread.get(key) or '') for key, _, _ in self.sidebar_columns)])
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self.sessions.addTopLevelItem(item)
            if i == self.active_thread:
                selected = item
        if selected:
            self.sessions.setCurrentItem(selected)
        self.sessions.blockSignals(False)
        self.sidebar_info.setText(f'{count} of {len(self.threads)} conversations')

    def open_selected_thread(self, item, _previous):
        if item and not self.loading:
            index = item.data(0, Qt.ItemDataRole.UserRole)
            if index != self.active_thread or (self.result is None and self.progress.isHidden()):
                self.open_thread(index)

    def open_thread(self, index):
        if self.viewer.export_root is None:
            self.status.setText('Choose an export directory before opening a conversation.')
            return
        self.active_thread = index
        self.reset_conversation()
        thread = self.threads[index]
        self.thread_title.setText(thread['name'])
        self.thread_cwd.setText('Working directory: ' + (thread.get('cwd') or 'Unknown'))
        self.thread_source.setText(thread.get('source_detail') or 'Rollout: ' + (
            thread.get('rollout_path') or 'Not recorded'))
        if index in self.cache:
            self.worker.invalidate()
            self.progress.hide()
            self.display_result(self.cache[index])
        else:
            self.progress.show()
            self.status.setText(f'Reading {self.provider.name} evidence for {thread["name"]}')
            self.transcript.replace([('loading', 'Reconstructing selected conversation…')])
            self.worker.start('reconstructed', reconstruct, self.provider, self.source,
                              thread, self.viewer.export_root)

    def reset_conversation(self):
        self.render_cancel.set()
        self.render_worker.invalidate()
        if self.index is not None:
            self.retained_kind = self.kind.currentText()
        self.result = self.index = None
        self.collapsed.clear()
        self.transcript.replace([], reset=True)
        self.export_actions.hide()
        if self.upload_dialog:
            self.upload_dialog.close()
            self.upload_dialog = None
        self.turn.blockSignals(True)
        self.turn.clear()
        self.turn.addItem('Entire conversation')
        self.turn.blockSignals(False)
        self.set_kinds((ALL_ENTRIES,))
        self.stats.clear()

    def display_result(self, result):
        self.result = result
        self.index = result.get('_search_index') or TranscriptIndex(result['turns'])
        self.turn.blockSignals(True)
        self.turn.clear()
        self.turn.addItem('Entire conversation')
        self.turn.addItems([f'{i + 1:02d} · {short(turn["title"],75)}' for i, turn in enumerate(result['turns'])])
        self.turn.blockSignals(False)
        summary = result['summary']
        self.stats.setText(f'{summary["turns"]} turns · {summary["activities"]} activities')
        if result.get('source_detail'):
            self.thread_source.setText(result['source_detail'])
        self.export_actions.setVisible(bool(export_folder(result)))
        self.set_kinds(self.index.filters, self.retained_kind)
        self.turn_changed()

    def set_kinds(self, choices, previous=None):
        previous = previous if previous is not None else self.kind.currentText()
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItems(choices)
        self.kind.setCurrentText(previous if previous in choices else ALL_ENTRIES)
        self.kind.blockSignals(False)

    def turn_changed(self):
        if self.index is not None:
            selected = self.turn.currentIndex() - 1
            self.set_kinds(self.index.turn_filters[selected] if selected >= 0 else self.index.filters)
            self.render()

    def render(self, *, keep_position=False):
        if self.index is None:
            return
        self.render_cancel.set()
        cancelled = self.render_cancel = Event()
        selected = self.turn.currentIndex()
        args = (self.index, self.search.text(), self.kind.currentText(), selected - 1 if selected > 0 else None,
                frozenset(self.collapsed), frozenset(), cancelled)

        def plan(_progress):
            return build_plan(*args), keep_position

        self.render_worker.start('rendered', plan)

    def apply_render(self, value):
        plan, keep_position = value
        if plan is None:
            return
        rows, _, total, hidden, styles = plan
        self.transcript.replace(rows, styles, keep_position=keep_position)
        status = f'{total} matching entries'
        self.status.setText(status + (f' · {hidden} collapsed' if hidden else ''))

    def toggle_prompt(self, key):
        self.collapsed.symmetric_difference_update({key})
        self.render(keep_position=True)

    def clear_filters(self):
        self.kind.setCurrentText(ALL_ENTRIES)
        self.search.clear()

    def open_export_folder(self):
        if directory := export_folder(self.result or {}):
            self.viewer.reveal(directory)

    def show_uploads(self):
        if directory := export_folder(self.result or {}):
            if self.upload_dialog is None:
                self.upload_dialog = UploadDialog(self, directory)
            self.upload_dialog.show()
            self.upload_dialog.raise_()

    def refresh_exports(self):
        self.export_path.setText(str(self.viewer.export_root))
        self.cache.clear()
        if self.active_thread is not None and not self.loading:
            self.open_thread(self.active_thread)

    def dispose(self):
        self.timer.stop()
        self.render_cancel.set()
        self.worker.close()
        self.render_worker.close()


class Viewer(QMainWindow):
    def __init__(self, export_root=None, *, script_directory=None):
        super().__init__()
        self.export_root = None
        export_error = None
        try:
            export_root = export_root or read_export_root(
                Path(script_directory or Path.cwd()).resolve(), preference_path())
            validate_export_root(export_root)
            self.export_root = export_root
        except (OSError, RuntimeError, ValueError) as error:
            export_error = f'Could not validate export directory · {error}'
        self.setWindowTitle('AgentSleuth — Agent Conversation Viewer')
        logo = QIcon(str(Path(__file__).with_name('assets') / 'agentsleuth-logo.png'))
        self.setWindowIcon(logo)
        self.resize(1390, 830)
        self.setMinimumSize(900, 620)
        self.scanner = None
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(10)
        masthead = QFrame()
        masthead.setObjectName('panel')
        heading = QHBoxLayout(masthead)
        heading.setContentsMargins(12, 6, 15, 6)
        mark = evidence_label('')
        mark.setPixmap(logo.pixmap(QSize(40, 40), self.devicePixelRatioF()))
        heading.addWidget(mark)
        heading.addWidget(evidence_label('AGENTSLEUTH', points=19, bold=True))
        heading.addStretch()
        add_button(heading, 'Scan for artifacts…', self.open_scanner, accent=True)
        layout.addWidget(masthead)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        for provider in PROVIDERS:
            pane = AgentPane(self, provider)
            self.tabs.addTab(pane, provider.name)
            if export_error:
                pane.status.setText(export_error)
        self.search_shortcut = QShortcut(QKeySequence('Ctrl+F'), self)
        self.search_shortcut.activated.connect(lambda: self.tabs.currentWidget().search.setFocus())

    def change_export_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose export directory', str(self.export_root or ''))
        if not path:
            return
        root = Path(path).expanduser().absolute()
        try:
            validate_export_root(root)
        except (OSError, RuntimeError, ValueError) as error:
            self.tabs.currentWidget().status.setText(f'Could not set export directory · {error}')
            return
        warning = None
        try:
            save_export_root(preference_path(), root)
        except (OSError, ValueError) as error:
            warning = f'Export directory selected for this run · could not save preference ({error})'
        if root != self.export_root:
            self.export_root = root
            for i in range(self.tabs.count()):
                self.tabs.widget(i).refresh_exports()
        if warning:
            self.tabs.currentWidget().status.setText(warning)

    def open_scanner(self):
        if self.scanner is None:
            self.scanner = ScanDialog(self)
            self.scanner.finished.connect(self._forget_scanner)
        self.scanner.show()
        self.scanner.raise_()

    def _forget_scanner(self):
        scanner, self.scanner = self.scanner, None
        if scanner is not None:
            scanner.deleteLater()

    def open_evidence_sources(self, sources, evidence_root):
        opened = []
        for hit in sources:
            if hit.source is None:
                continue
            panes = [self.tabs.widget(i) for i in range(self.tabs.count())]
            provider_panes = [pane for pane in panes if pane.provider.name == hit.agent]
            identity = hit.source, evidence_root
            pane = next((p for p in provider_panes if p.scan_source == identity
                         and (p.source == hit.source or (p.loading and p.path.text() == str(hit.source)))), None)
            if pane:
                opened.append(pane)
                continue
            pane = next((p for p in provider_panes if p.source is None and not p.loading), None)
            if pane is None:
                pane = AgentPane(self, provider_panes[0].provider, closable=True)
                label = f'{hit.agent} · {hit.path.name}'
                title = label
                suffix = 2
                titles = {self.tabs.tabText(i) for i in range(self.tabs.count())}
                while title in titles:
                    title = f'{label} ({suffix})'
                    suffix += 1
                self.tabs.addTab(pane, title)
            pane.scan_source = identity
            pane.path.setText(str(hit.source))
            pane.load_source()
            opened.append(pane)
        if opened:
            self.tabs.setCurrentWidget(opened[0])
        return bool(opened)

    def close_source_tab(self, pane):
        self.tabs.removeTab(self.tabs.indexOf(pane))
        pane.dispose()
        pane.deleteLater()

    def reveal(self, path):
        try:
            if not path.exists():
                raise FileNotFoundError(path)
            if sys.platform == 'win32':
                if path.is_dir():
                    os.startfile(str(path))
                else:
                    reveal_file(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(path)] if path.is_dir() else ['open', '-R', str(path)])
            else:
                subprocess.Popen(['xdg-open', str(path if path.is_dir() else path.parent)])
        except (OSError, ValueError) as error:
            self.tabs.currentWidget().status.setText(f'Could not show file location · {error}')

    def closeEvent(self, event):
        if self.scanner:
            self.scanner.reject()
        for i in range(self.tabs.count()):
            self.tabs.widget(i).dispose()
        super().closeEvent(event)


def sample_turns(size):
    return [
        {'title': f'Prompt {start // 20 + 1}',
         'entries': [{'ordinal': i + 1, 'kind': 'message',
                      'role': 'user' if i == start else 'assistant',
                      'text': f'Entry stress-{i:04d}'} for i in range(start, min(start + 20, size))]}
        for start in range(0, size, 20)
    ]


def benchmark(app, viewer, size):
    pane = viewer.tabs.currentWidget()
    turns = sample_turns(size)
    start = perf_counter()
    pane.display_result({'turns': turns, 'summary': {'turns': len(turns), 'activities': 0}})
    deadline = perf_counter() + 10
    while not pane.transcript.live and perf_counter() < deadline:
        app.processEvents()
        sleep(.001)
    app.processEvents()
    pane.transcript.viewport().repaint()
    first = perf_counter()
    assert pane.transcript.live
    assert len(pane.transcript.rows) == size + len(turns)
    mounted = len(pane.transcript.live)
    bar = pane.transcript.verticalScrollBar()
    bar.setValue(bar.maximum())
    for _ in range(10):
        app.processEvents()
    assert len(pane.transcript.rows) - 1 in pane.transcript.live
    print(f'{size:,} entries: index, plan, and first paint {(first-start)*1000:.1f} ms; '
          f'{mounted} rows mounted initially; last row reached in {(perf_counter()-first)*1000:.1f} ms')


def configure_application(app):
    # Qt's Windows offscreen backend starts without a system font database.
    if sys.platform == 'win32' and app.platformName() == 'offscreen':
        fonts = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
        for name in ('consola.ttf', 'consolab.ttf', 'segoeui.ttf'):
            if (path := fonts / name).is_file():
                QFontDatabase.addApplicationFont(str(path))
    app.setStyle('Fusion')
    app.setFont(QFont('Consolas', 10))
    app.setStyleSheet(THEME)


def main(script_path=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--demo', action='store_true', help='show a synthetic 1,000-entry conversation')
    mode.add_argument('--benchmark', type=int, metavar='ROWS', help='time the Qt transcript and exit')
    parser.add_argument('--export-root', type=Path, help='separate destination for recovered files')
    args = parser.parse_args()
    if args.benchmark is not None and args.benchmark < 1:
        parser.error('--benchmark requires a positive row count')
    app = QApplication([])
    configure_application(app)
    script_directory = Path(script_path).resolve().parent if script_path is not None else Path.cwd()
    viewer = Viewer(args.export_root, script_directory=script_directory)
    viewer.show()
    if args.benchmark is not None:
        app.processEvents()
        benchmark(app, viewer, args.benchmark)
        viewer.close()
        return 0
    if args.demo:
        turns = sample_turns(1000)
        pane = viewer.tabs.currentWidget()
        pane.thread_title.setText('Sample conversation')
        pane.display_result({'turns': turns, 'summary': {'turns': len(turns), 'activities': 0}})
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
