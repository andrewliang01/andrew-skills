"""打开最大化的 Edge 看板窗口，保留窗口标题栏。"""

import os
import subprocess
import sys
from time import monotonic, sleep


def open_edge(url):
    """
    打开 Edge 的应用窗口并使用浏览器的最大化启动参数。
    输入本机看板 URL，返回启动的进程句柄。
    """
    return subprocess.Popen(
        ["microsoft-edge", f"--app={url}", "--start-maximized"],
        stdin=subprocess.DEVNULL, start_new_session=True,
    )


def open_maximized(url):
    """
    复用准确匹配的看板窗口，必要时等待新窗口就绪。
    输入本机看板 URL，通过 X11 退出旧全屏状态、最大化并前置窗口。
    """
    try:
        from Xlib import X, Xatom, display, error
        from Xlib.protocol.event import ClientMessage
    except ImportError:
        open_edge(url)
        return
    try:
        connection = display.Display(os.environ.get("DISPLAY"))
    except (OSError, error.DisplayError):
        open_edge(url)
        return

    try:
        root = connection.screen().root
        atom = connection.intern_atom
        fullscreen = atom("_NET_WM_STATE_FULLSCREEN")
        horizontal = atom("_NET_WM_STATE_MAXIMIZED_HORZ")
        vertical = atom("_NET_WM_STATE_MAXIMIZED_VERT")
        started = False
        deadline = monotonic() + 12
        while monotonic() < deadline:
            clients = root.get_full_property(atom("_NET_CLIENT_LIST_STACKING"), Xatom.WINDOW)
            for identifier in reversed(clients.value if clients else ()):
                window = connection.create_resource_object("window", int(identifier))
                try:
                    title = window.get_full_property(atom("_NET_WM_NAME"), atom("UTF8_STRING"))
                    window_class = window.get_wm_class()
                except error.BadWindow:
                    continue
                # 同时匹配专用窗口的类和标题，避免影响普通 Edge 标签页。
                if not window_class or window_class[0] != "127.0.0.1":
                    continue
                if not title or title.value.decode(errors="replace") != "Andrew · GPU 资源看板":
                    continue
                for message, fields in (
                    ("_NET_WM_STATE", [0, fullscreen, 0, 1, 0]),
                    ("_NET_WM_STATE", [1, horizontal, vertical, 1, 0]),
                    ("_NET_ACTIVE_WINDOW", [1, X.CurrentTime, 0, 0, 0]),
                ):
                    event = ClientMessage(window=window, client_type=atom(message), data=(32, fields))
                    root.send_event(event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
                connection.sync()
                return
            if not started:
                open_edge(url)
                started = True
            sleep(0.25)
    finally:
        connection.close()


if __name__ == "__main__":
    open_maximized(sys.argv[1])
