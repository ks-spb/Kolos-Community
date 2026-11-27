"""CV core based on Glaz components.

Keep desktop-only dependencies lazy so model/CLI tests can import lightweight
submodules (for example glaz_ipc) on headless systems.
"""

__all__ = ["screen"]


def __getattr__(name):
    if name == "screen":
        from .compat_adapter import screen
        return screen
    raise AttributeError(name)
