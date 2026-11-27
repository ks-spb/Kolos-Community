"""Запуск Kolos (main.py) как подпроцесса: stdout/stderr в UI, stdin из строки ввода."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

StreamName = str  # "stdout" | "stderr" | "_exit"


def project_root_from_glaz_file(glaz_module_file: str | Path) -> Path:
    """Корень репозитория Kolos: родитель каталога Glaz."""
    return Path(glaz_module_file).resolve().parent.parent


class KolosSubprocessController:
    """Управляет жизненным циклом ``main.py`` и потоками чтения stdout/stderr."""

    def __init__(
        self,
        project_root: Path,
        on_event: Callable[[StreamName, str], None],
    ) -> None:
        self._project_root = project_root
        self._on_event = on_event
        self._proc: Optional[subprocess.Popen[str]] = None
        self._threads: list[threading.Thread] = []

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, *, monitor_idx: int | None = None, engine: str = "states",
              ipc_dir: str | None = None, session: str | None = None,
              glaz_pid: int = 0) -> str:
        """Запуск Kolos. Возвращает сообщение об ошибке или пустую строку при успехе."""
        if self.is_running:
            return "Kolos уже запущен; сначала остановите процесс"
        if engine != "states":
            return "Legacy отключён. Поддерживается только Состояния и цели (ПК)."
        main_py = self._project_root / "main.py"

        self._engine = engine
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        # Иначе на Windows пайп получает cp1251/OEM, а читаем как UTF-8 — «» вместо русского текста.
        env["PYTHONIOENCODING"] = "utf-8"
        if monitor_idx is not None:
            env["KOLOS_MONITOR_IDX"] = str(int(monitor_idx))

        command = []
        if engine == "states":
            if not ipc_dir or not session:
                return "States требует сеанс наблюдений Glaz"
            if not (self._project_root / "kolos_states" / "cli.py").is_file():
                return "Не установлен kolos_states; обновите проект целиком"
            command = [sys.executable, "-m", "kolos_states.cli", "--ipc", ipc_dir, "--session", session, "--glaz-pid", str(glaz_pid)]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._proc = subprocess.Popen(
                command,
                cwd=str(self._project_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creationflags,
            )
        except OSError as e:
            return f"Не удалось запустить Kolos: {e}"

        assert self._proc.stdout is not None and self._proc.stderr is not None

        proc = self._proc
        self._threads = [
            threading.Thread(
                target=self._read_stream,
                args=(self._proc.stdout, "stdout"),
                daemon=True,
            ),
            threading.Thread(
                target=self._read_stream,
                args=(self._proc.stderr, "stderr"),
                daemon=True,
            ),
            threading.Thread(target=self._wait_process, args=(proc,), daemon=True),
        ]
        for t in self._threads:
            t.start()
        return ""

    def send_line(self, text: str) -> bool:
        """Отправить строку в stdin Kolos; вернуть успех записи в пайп."""
        if not self.is_running or self._proc is None or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write(text if text.endswith("\n") else text + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return False
        return True

    def stop(self, timeout_sec: float = 3.0) -> None:
        """Завершить Kolos."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            if getattr(self, "_engine", "legacy") == "states":
                self.send_line("/quit")
                try:
                    self._proc.wait(timeout=min(1.0, timeout_sec))
                except subprocess.TimeoutExpired:
                    pass
            try:
                if self._proc.poll() is None:
                    self._proc.terminate()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                try:
                    self._proc.kill()
                except OSError:
                    pass
        self._proc = None
        self._threads = []

    def _read_stream(self, stream, name: StreamName) -> None:
        for line in iter(stream.readline, ""):
            self._on_event(name, line.rstrip("\r\n"))
        try:
            stream.close()
        except OSError:
            pass

    def _wait_process(self, proc) -> None:
        code = proc.wait()
        # Ignore termination of an old child after a new one has started.
        if self._proc is proc:
            self._on_event("_exit", str(code))
