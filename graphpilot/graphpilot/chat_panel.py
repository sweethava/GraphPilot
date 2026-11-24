"""Dockable GraphPilot chat panel (basic widget fallback) inside Substance Designer.

Runs Claude Code headless (`claude -p ... --output-format stream-json`) and keeps
the conversation via --resume. Claude talks back to Designer through the
substance-designer MCP server -> this plugin's TCP bridge.
"""
import html
import json
import os
import shutil
import sys

from PySide6 import QtCore, QtGui, QtWidgets

WORKDIR = os.path.expanduser("~")
ALLOWED_TOOLS = ["mcp__substance-designer", "Read", "Glob", "Grep", "WebSearch", "WebFetch"]
SYSTEM_PROMPT = (
    "You are running inside a chat panel docked in Adobe Substance 3D Designer. "
    "The user sees your replies in a small panel, so keep them concise. "
    "Use the substance-designer MCP tools (sd_*) to inspect and edit the graph that is open in Designer, "
    "and sd_render_node to look at results. Reply in the user's language."
)


HERE = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER = os.path.join(HERE, "mcp_server.py")
IS_WIN = sys.platform.startswith("win")


def _find_claude():
    """GUI apps (esp. on macOS) don't get the shell PATH, so also try the usual install places."""
    home = os.path.expanduser("~")
    cands = [shutil.which("claude")]
    if IS_WIN:
        cands += [os.path.join(home, ".local", "bin", "claude.exe"),
                  os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")]
    else:
        cands += [os.path.join(home, ".local", "bin", "claude"), os.path.join(home, ".claude", "local", "claude"),
                  "/opt/homebrew/bin/claude", "/usr/local/bin/claude", os.path.join(home, ".npm-global", "bin", "claude")]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def _find_python():
    """Python to run mcp_server.py: the one bundled with Designer, else a system one."""
    exe_dir = os.path.dirname(sys.executable)
    cands = []
    if IS_WIN:
        cands += [os.path.join(exe_dir, "plugins", "pythonsdk", "python.exe")]
    else:
        # macOS bundle: .../Contents/MacOS/<exe> ; pythonsdk lives under Contents/Plugins or Contents/Resources
        root = os.path.dirname(exe_dir)
        for sub in ("Plugins/pythonsdk/bin", "plugins/pythonsdk/bin", "Resources/plugins/pythonsdk/bin",
                    "MacOS/plugins/pythonsdk/bin", "plugins/pythonsdk"):
            for name in ("python3", "python"):
                cands.append(os.path.join(root, sub, name))
        cands.append(os.path.join(exe_dir, "plugins", "pythonsdk", "bin", "python3"))
    if os.path.basename(sys.executable).lower().startswith("python"):
        cands.append(sys.executable)
    cands += [shutil.which("python3"), shutil.which("python")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def claude_base_args():
    """Flags shared by both panels: bundled MCP server (no manual `claude mcp add` needed) + tool permissions."""
    py = _find_python()
    args = []
    if py:
        cfg = {"mcpServers": {"substance-designer": {"command": py, "args": ["-I", MCP_SERVER]}}}
        args += ["--mcp-config", json.dumps(cfg), "--strict-mcp-config"]
    args += ["--append-system-prompt", SYSTEM_PROMPT, "--allowedTools", *ALLOWED_TOOLS]
    return args


def child_env():
    env = QtCore.QProcessEnvironment.systemEnvironment()
    # Designer's embedded Python vars must not leak into child processes
    for k in ("PYTHONHOME", "PYTHONPATH"):
        env.remove(k)
    return env


class ClaudeChat(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session_id = None
        self.proc = None
        self._buf = b""
        self._md = ""          # finished transcript (markdown)
        self._live = ""        # current assistant text being streamed

        self.view = QtWidgets.QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.input = QtWidgets.QPlainTextEdit()
        self.input.setPlaceholderText("Напиши Claude… (Ctrl+Enter — отправить)")
        self.input.setFixedHeight(80)
        self.input.installEventFilter(self)
        self.send_btn = QtWidgets.QPushButton("Send")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.new_btn = QtWidgets.QPushButton("New chat")
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color: gray")
        self.stop_btn.setEnabled(False)

        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(self.status, 1)
        btns.addWidget(self.new_btn)
        btns.addWidget(self.stop_btn)
        btns.addWidget(self.send_btn)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.input)
        lay.addLayout(btns)

        self.send_btn.clicked.connect(self.send)
        self.stop_btn.clicked.connect(self.stop)
        self.new_btn.clicked.connect(self.new_chat)
        self._render()

    # ---------------------------------------------------------------- ui
    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == QtCore.QEvent.KeyPress:
            if ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and \
                    ev.modifiers() & QtCore.Qt.ControlModifier:
                self.send()
                return True
        return super().eventFilter(obj, ev)

    def _render(self):
        md = self._md + (self._live if self._live else "")
        if not md:
            md = "_Claude готов. Спроси что-нибудь про открытый граф._"
        self.view.setMarkdown(md)
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _append(self, text):
        self._md += text
        self._render()

    def new_chat(self):
        self.stop()
        self.session_id = None
        self._md = ""
        self._live = ""
        self.status.setText("new session")
        self._render()

    # ---------------------------------------------------------------- process
    def send(self):
        msg = self.input.toPlainText().strip()
        if not msg or (self.proc and self.proc.state() != QtCore.QProcess.NotRunning):
            return
        self.input.clear()
        self._append("\n\n---\n\n**Ты:** " + msg + "\n\n")
        args = ["-p", msg, "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", *claude_base_args()]
        if self.session_id:
            args += ["--resume", self.session_id]
        self.proc = QtCore.QProcess(self)
        self.proc.setWorkingDirectory(WORKDIR)
        self.proc.setProcessEnvironment(child_env())
        self.proc.readyReadStandardOutput.connect(self._on_stdout)
        self.proc.readyReadStandardError.connect(self._on_stderr)
        self.proc.finished.connect(self._on_finished)
        self.proc.errorOccurred.connect(self._on_error)
        self._buf = b""
        self._live = ""
        self.proc.start(_find_claude() or "claude", args)
        self.proc.closeWriteChannel()
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("thinking…")

    def stop(self):
        if self.proc and self.proc.state() != QtCore.QProcess.NotRunning:
            self.proc.kill()

    def _on_error(self, err):
        self._append("\n\n> ⚠ не удалось запустить claude: %s\n" % err)

    def _on_stderr(self):
        data = bytes(self.proc.readAllStandardError()).decode("utf-8", "replace").strip()
        if data:
            print("[GraphPilot] claude stderr:", data)

    def _on_finished(self, *a):
        self._on_stdout()
        if self._live:
            self._md += self._live
            self._live = ""
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self.status.text() in ("thinking…",) or self.status.text().startswith("tool"):
            self.status.setText("done")
        self._render()

    def _on_stdout(self):
        if not self.proc:
            return
        self._buf += bytes(self.proc.readAllStandardOutput())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line.decode("utf-8", "replace"))
            except Exception:
                continue
            self._handle(ev)
        self._render()

    def _handle(self, ev):
        t = ev.get("type")
        if ev.get("session_id"):
            self.session_id = ev["session_id"]
        if t == "stream_event":
            e = ev.get("event", {})
            if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta":
                if not self._live:
                    self._live = "**Claude:** "
                self._live += e["delta"].get("text", "")
        elif t == "assistant":
            # full message arrived: commit streamed text, show tool calls
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    if self._live:
                        self._md += self._live + "\n\n"
                        self._live = ""
                    else:
                        self._md += "**Claude:** " + block.get("text", "") + "\n\n"
                elif block.get("type") == "tool_use":
                    if self._live:
                        self._md += self._live + "\n\n"
                        self._live = ""
                    name = block.get("name", "").replace("mcp__substance-designer__", "")
                    self._md += "`⚙ %s`\n\n" % name
                    self.status.setText("tool: " + name)
        elif t == "result":
            if ev.get("is_error"):
                self._md += "\n\n> ⚠ %s\n\n" % (ev.get("result") or ev.get("subtype"))
            cost = ev.get("total_cost_usd")
            self.status.setText("done" + (" · $%.3f" % cost if cost else ""))


_dock_widget = None


def create_dock(ui_mgr):
    """Create the dock via Designer's UI manager (Window menu lists it)."""
    global _dock_widget
    dock = ui_mgr.newDockWidget("graphpilot_panel", "GraphPilot")
    chat = ClaudeChat(dock)
    lay = QtWidgets.QVBoxLayout(dock)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(chat)
    _dock_widget = chat
    return chat
