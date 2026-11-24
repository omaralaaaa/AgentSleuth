"""AgentSleuth's desktop UI, with lazy Qt imports for headless parsers."""

__all__ = ["App", "main"]


def __getattr__(name):
    if name in __all__:
        from .qt_app import Viewer, main
        return Viewer if name == 'App' else main
    raise AttributeError(name)
