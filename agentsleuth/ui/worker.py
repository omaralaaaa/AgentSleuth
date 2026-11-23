"""Run one agent's evidence jobs independently of Tk and other agents."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event

from ..core.search import TranscriptIndex


class _Superseded(Exception):
    pass


def _run(results, request, cancelled, completed, action, args):
    def progress(message):
        if cancelled.is_set():
            raise _Superseded
        results.put((request, 'progress', message))

    try:
        result = action(*args, progress)
    except _Superseded:
        return
    except Exception as error:
        completed, result = 'error', str(error)
    if not cancelled.is_set():
        results.put((request, completed, result))


def load_threads(parser, path, _progress):
    path = path.expanduser().resolve()
    if not path.is_file() and not (getattr(parser, 'accepts_directory', False) and path.is_dir()):
        raise FileNotFoundError(f'{parser.source_hint}. File not found: {path}')
    return path, parser.load_threads(path)


def reconstruct(parser, path, thread, output_root, progress):
    result = parser.reconstruct_from_thread(path, thread, output_root, progress)
    progress('Indexing reconstructed conversation…')
    result['_search_index'] = TranscriptIndex(result['turns'])
    return result


class AgentWorker:
    def __init__(self, name):
        self.results = Queue()
        self.request = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f'AgentSleuth-{name}')
        self._future = None
        self._cancelled = Event()

    def invalidate(self):
        self.request += 1
        self._cancelled.set()
        if self._future is not None:
            self._future.cancel()
            self._future = None

    def start(self, completed, action, *args):
        self.invalidate()
        self._cancelled = Event()
        self._future = self._executor.submit(
            _run, self.results, self.request, self._cancelled, completed, action, args
        )

    def close(self):
        self.invalidate()
        self._executor.shutdown(wait=False, cancel_futures=True)
