"""
GraphPilot: AI chat panel + MCP bridge for Adobe Substance 3D Designer (works with Claude Code).

Opens a TCP server on 127.0.0.1:9881 (newline-delimited JSON). Each request
is executed on the Qt main thread (the SD API is not thread-safe).

Every request must carry the session token. A new random token is made on each
start and written, with the port, to <data dir>/bridge.json (a per-user folder),
so only programs running as this user can talk to the bridge.

Request:  {"id": 1, "token": "...", "cmd": "exec", "code": "..."}      -> runs python
          {"id": 2, "token": "...", "cmd": "call", "fn": "graph_info", "args": {...}}
Response: {"id": 1, "ok": true, "result": ..., "stdout": "..."}
"""
import ast
import hmac
import io
import json
import os
import secrets
import socket
import sys
import threading
import traceback
import contextlib

from PySide6 import QtCore

HOST = "127.0.0.1"
PORT = 9881

if os.environ.get("APPDATA"):
    DATA_DIR = os.path.join(os.environ["APPDATA"], "GraphPilot")
elif sys.platform == "darwin":
    DATA_DIR = os.path.expanduser("~/Library/Application Support/GraphPilot")
else:
    DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "GraphPilot")
BRIDGE_FILE = os.path.join(DATA_DIR, "bridge.json")

_server = None


def _write_bridge_file(token):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = BRIDGE_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # owner-only on macOS/Linux
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"host": HOST, "port": PORT, "token": token, "pid": os.getpid()}, f)
    os.replace(tmp, BRIDGE_FILE)


class _Dispatcher(QtCore.QObject):
    run = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.run.connect(self._on_run, QtCore.Qt.QueuedConnection)

    @QtCore.Slot(object)
    def _on_run(self, job):
        job()


def _jsonable(o):
    from . import helpers
    return helpers.to_py(o)


class _Server:
    def __init__(self):
        self.dispatcher = _Dispatcher()
        self.namespace = None
        self.sock = None
        self.alive = True
        self.token = secrets.token_urlsafe(32)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    # ---- executed on main thread ----
    def _ns(self):
        if self.namespace is None:
            import sd
            from . import helpers
            ctx = sd.getContext()
            app = ctx.getSDApplication()
            self.namespace = {
                "sd": sd,
                "ctx": ctx,
                "app": app,
                "pkg_mgr": app.getPackageMgr(),
                "ui_mgr": app.getQtForPythonUIMgr(),
                "H": helpers,
                "__name__": "__claude__",
            }
            exec("from sd.api.sdbasetypes import *\n"
                 "from sd.api.sdproperty import SDPropertyCategory\n", self.namespace)
        return self.namespace

    def _execute(self, req):
        from . import helpers
        out = io.StringIO()
        resp = {"id": req.get("id")}
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                cmd = req.get("cmd", "exec")
                if cmd == "exec":
                    ns = self._ns()
                    ns.pop("result", None)
                    tree = ast.parse(req.get("code", "").lstrip("﻿"), "<claude>", "exec")
                    value = None
                    if tree.body and isinstance(tree.body[-1], ast.Expr):
                        last = ast.Expression(tree.body.pop().value)
                        exec(compile(tree, "<claude>", "exec"), ns)
                        value = eval(compile(last, "<claude>", "eval"), ns)
                    else:
                        exec(compile(tree, "<claude>", "exec"), ns)
                    if "result" in ns:
                        value = ns["result"]
                    result = value
                elif cmd == "call":
                    fn = getattr(helpers, req["fn"])
                    result = fn(**(req.get("args") or {}))
                elif cmd == "ping":
                    result = "pong"
                else:
                    raise ValueError("unknown cmd %r" % cmd)
            resp["ok"] = True
            resp["result"] = helpers.to_py(result)
        except BaseException:  # sd.api APIException derives from BaseException, not Exception
            resp["ok"] = False
            resp["error"] = traceback.format_exc()
        resp["stdout"] = out.getvalue()
        return resp

    # ---- worker threads ----
    def _run_on_main(self, req):
        done = threading.Event()
        box = {}

        def job():
            try:
                box["r"] = self._execute(req)
            finally:
                done.set()

        self.dispatcher.run.emit(job)
        if not done.wait(req.get("timeout", 300)):
            return {"id": req.get("id"), "ok": False,
                    "error": "timeout waiting for Designer main thread"}
        return box["r"]

    def _handle(self, conn):
        with conn:
            f = conn.makefile("rwb")
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line.decode("utf-8"))
                    if not hmac.compare_digest(str(req.get("token", "")).encode(), self.token.encode()):
                        resp = {"id": req.get("id"), "ok": False,
                                "error": "GraphPilot bridge: missing or wrong token (see bridge.json)"}
                    else:
                        resp = self._run_on_main(req)
                except Exception:
                    resp = {"ok": False, "error": traceback.format_exc()}
                try:
                    data = json.dumps(resp, default=str)
                except Exception:
                    data = json.dumps({"id": resp.get("id"), "ok": False,
                                       "error": "unserializable result"})
                f.write(data.encode("utf-8") + b"\n")
                f.flush()

    def _serve(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1) if hasattr(socket, "SO_EXCLUSIVEADDRUSE") else None
        s.bind((HOST, PORT))
        s.listen(128)   # tool calls can arrive in bursts (parallel MCP calls)
        self.sock = s
        try:
            _write_bridge_file(self.token)
        except Exception:
            traceback.print_exc()
        print("[GraphPilot] listening on %s:%d" % (HOST, PORT))
        while self.alive:
            try:
                conn, _ = s.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def stop(self):
        self.alive = False
        try:
            self.sock.close()
        except Exception:
            pass
        try:
            with open(BRIDGE_FILE, encoding="utf-8") as f:
                mine = json.load(f).get("token") == self.token
            if mine:
                os.remove(BRIDGE_FILE)
        except Exception:
            pass


def initializeSDPlugin():
    global _server
    try:
        _server = _Server()
    except Exception:
        traceback.print_exc()
    try:
        import sd
        ui = sd.getContext().getSDApplication().getQtForPythonUIMgr()
        try:
            from . import chat_qml
            chat_qml.create_dock(ui)
        except Exception:
            traceback.print_exc()
            print("[GraphPilot] QML panel failed, using basic panel")
            from . import chat_panel
            chat_panel.create_dock(ui)
    except Exception:
        traceback.print_exc()


def uninitializeSDPlugin():
    global _server
    if _server:
        _server.stop()
        _server = None
