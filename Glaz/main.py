#!/usr/bin/env python3
"""
Glaz - Программа для захвата и анализа экрана
Точка входа в приложение
"""

import sys
import os
from pathlib import Path

import tkinter as tk

# Запуск из папки Glaz не видит соседний пакет cv_core.
# Добавляем корень репозитория в sys.path до импортов приложения.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from states_app import IntegratedScreenCaptureApp
from studio_app import NeuralStudioApp

# The classic workspace remains an explicit rollback, not a second engine.
ScreenCaptureApp = IntegratedScreenCaptureApp if os.environ.get("GLAZ_UI") == "classic" else NeuralStudioApp


def main():
    """Запуск приложения."""
    root = tk.Tk()
    ScreenCaptureApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
