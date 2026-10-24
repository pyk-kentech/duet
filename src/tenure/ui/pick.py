"""OS 폴더 고르기 창 (DESIGN.md 28.9). UI 서버가 `tenure _pick` 으로 따로 띄운다(창이 서버 스레드를 막지 않게)."""

from __future__ import annotations


def pick_folder(initial: str = "") -> str:
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tkinter.TclError:
        pass
    root.update()
    path = filedialog.askdirectory(parent=root, initialdir=initial or None, title="작업 폴더 고르기", mustexist=False)
    return path or ""
