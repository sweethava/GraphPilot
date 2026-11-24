"""QML chat panel for Claude inside Substance Designer.

Python = backend (runs `claude -p` with stream-json, parses events, stores chats),
QML (chat.qml) = UI. Falls back to the widget panel if QML fails.
"""
import base64
import datetime
import json
import os
import re
import shutil
import sys
import threading
import time

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot, Qt

from . import chat_panel  # reuse claude path, prompt, tool list
from . import agents
from . import i18n

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_URL = "https://github.com/sweethava/GraphPilot"
AUTHOR_URL = "https://github.com/sweethava"


def _plugin_version():
    try:
        with open(os.path.join(os.path.dirname(HERE), "pluginInfo.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "")
    except Exception:
        return ""


VERSION = _plugin_version()
if os.environ.get("APPDATA"):
    DATA_DIR = os.path.join(os.environ["APPDATA"], "GraphPilot")
elif sys.platform == "darwin":
    DATA_DIR = os.path.expanduser("~/Library/Application Support/GraphPilot")
else:
    DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "GraphPilot")
CHAT_DIR = os.path.join(DATA_DIR, "chats")
INDEX_PATH = os.path.join(CHAT_DIR, "index.json")
IMG_DIR = os.path.join(DATA_DIR, "images")   # persistent, so history thumbnails survive restarts
IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tga", ".tif", ".tiff"}
MAX_IMAGES = 6
FONTS = ["onest", "inter", "system"]
_FONT_FILES = {"onest": "Onest-Variable.ttf", "inter": "InterVariable.ttf"}
_font_families = {}


def _settings():
    return QtCore.QSettings("GraphPilot", "GraphPilot")


def _migrate_legacy():
    """Pre-release builds were called 'claude_mcp_bridge': move their chats and settings over once."""
    old = os.path.join(os.path.dirname(DATA_DIR), "claude_sd_chat")
    if os.path.isdir(old) and not os.path.exists(DATA_DIR):
        try:
            shutil.move(old, DATA_DIR)
            old_url, new_url = QUrl.fromLocalFile(old).toString(), QUrl.fromLocalFile(DATA_DIR).toString()
            for fn in os.listdir(CHAT_DIR) if os.path.isdir(CHAT_DIR) else []:
                if fn.endswith(".json") and fn != "index.json":
                    p = os.path.join(CHAT_DIR, fn)
                    with open(p, encoding="utf-8") as f:
                        txt = f.read()
                    if old_url in txt:
                        with open(p, "w", encoding="utf-8") as f:
                            f.write(txt.replace(old_url, new_url))
        except Exception as e:
            print("[GraphPilot] migrating old chats failed:", e)
    st = _settings()
    if not st.allKeys():
        legacy = QtCore.QSettings("claude_mcp_bridge", "chat")
        for k in legacy.allKeys():
            st.setValue(k, legacy.value(k))


def load_fonts():
    for key, fn in _FONT_FILES.items():
        if key not in _font_families:
            fid = QtGui.QFontDatabase.addApplicationFont(os.path.join(HERE, "fonts", fn))
            fams = QtGui.QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            _font_families[key] = fams[0] if fams else ""
    _font_families["system"] = QtGui.QGuiApplication.font().family()


_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUM = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")


def pretty_md(text):
    """Render lists as compact '•' lines (Qt's markdown list indent is huge)."""
    out, in_code = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        m = _BULLET.match(line)
        n = _NUM.match(line) if not m else None
        if m or n:
            depth = len((m or n).group(1).replace("\t", "  ")) // 2
            pad = "&nbsp;" * (2 + 4 * depth)
            body = m.group(2) if m else n.group(3)
            marker = "•" if m else n.group(2) + "."
            # hard line break on the previous line so items don't merge into one paragraph
            if out and out[-1].strip():
                out[-1] = out[-1].rstrip() + "  "
            out.append("%s%s&nbsp;%s  " % (pad, marker, body))
        elif not line.strip():
            # Qt draws markdown paragraphs with no gap: insert a visible empty line
            if out and out[-1].strip() and out[-1] != "&nbsp;":
                out += ["", "&nbsp;", ""]
        else:
            out.append(line)
    return "\n".join(out)


# ======================================================================= chat list
class ChatListModel(QtCore.QAbstractListModel):
    """Chats sorted by last update. Incremental updates, so a long list doesn't reset/scroll-jump."""
    IdRole, TitleRole, WhenRole, CurrentRole = range(Qt.UserRole + 1, Qt.UserRole + 5)

    def __init__(self, backend):
        super().__init__(backend)
        self.b = backend
        self._all = []        # [{id, title, updated, custom}]
        self._rows = []       # filtered view of _all
        self._filter = ""

    def roleNames(self):
        return {self.IdRole: b"chatId", self.TitleRole: b"title", self.WhenRole: b"when",
                self.CurrentRole: b"current"}

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        c = self._rows[index.row()]
        if role == self.IdRole:
            return c["id"]
        if role in (self.TitleRole, Qt.DisplayRole):
            return c["title"]
        if role == self.WhenRole:
            return self.b._when(c["updated"])
        if role == self.CurrentRole:
            return c["id"] == self.b._chat_id
        return None

    countChanged = Signal()

    def _get_total(self):
        return len(self._all)

    total = Property(int, _get_total, notify=countChanged)

    def _match(self, c):
        return not self._filter or self._filter in c["title"].lower()

    def reset(self, items):
        self.beginResetModel()
        self._all = sorted(items, key=lambda c: -c["updated"])
        self._rows = [c for c in self._all if self._match(c)]
        self.endResetModel()
        self.countChanged.emit()

    @Slot(str)
    def setFilter(self, text):
        text = (text or "").strip().lower()
        if text != self._filter:
            self._filter = text
            self.beginResetModel()
            self._rows = [c for c in self._all if self._match(c)]
            self.endResetModel()

    def get(self, cid):
        return next((c for c in self._all if c["id"] == cid), None)

    def _row(self, cid):
        return next((i for i, c in enumerate(self._rows) if c["id"] == cid), -1)

    def upsert(self, entry):
        """Insert or update a chat and move it to the top."""
        self._all = [c for c in self._all if c["id"] != entry["id"]]
        self._all.insert(0, entry)
        r = self._row(entry["id"])
        if r >= 0:
            self._rows[r] = entry
            if r > 0:
                self.beginMoveRows(QtCore.QModelIndex(), r, r, QtCore.QModelIndex(), 0)
                self._rows.insert(0, self._rows.pop(r))
                self.endMoveRows()
            self.dataChanged.emit(self.index(0), self.index(0))
        elif self._match(entry):
            self.beginInsertRows(QtCore.QModelIndex(), 0, 0)
            self._rows.insert(0, entry)
            self.endInsertRows()
        self.countChanged.emit()

    def remove(self, cid):
        self._all = [c for c in self._all if c["id"] != cid]
        r = self._row(cid)
        if r >= 0:
            self.beginRemoveRows(QtCore.QModelIndex(), r, r)
            self._rows.pop(r)
            self.endRemoveRows()
        self.countChanged.emit()

    def refresh(self, *cids):
        """Re-read roles (current marker, relative dates) for given ids, or all rows."""
        if not self._rows:
            return
        if not cids:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1))
            return
        for cid in cids:
            r = self._row(cid)
            if r >= 0:
                self.dataChanged.emit(self.index(r), self.index(r))


# ======================================================================= backend
class ChatBackend(QObject):
    messageAppended = Signal(str, str, str)   # role, text, imageUrl
    lastTextUpdated = Signal(str)
    busyChanged = Signal()
    statusChanged = Signal()
    attachmentChanged = Signal()
    cleared = Signal()

    def __init__(self, ui_mgr=None, parent=None):
        super().__init__(parent)
        self.ui_mgr = ui_mgr
        self.proc = None
        self.session_id = None
        self._buf = b""
        self._live = None          # text of streaming assistant message, or None
        self._busy = False
        self._status = ""
        self._phase = ""           # "", thinking, tool, writing
        self._attach = ""
        self._attach_label = ""
        self._attach_nodes = None   # (graph identifier, [node ids]) behind the node chip
        self._last_prompt = ""
        self._images = []          # local paths of attached screenshots
        self._quiet_results = set()  # tool_use ids whose image results are not shown
        self._stderr = ""
        st = _settings()
        if st.contains("model") and not st.contains("model/claude"):   # pre-agents settings
            st.setValue("model/claude", st.value("model"))
            st.remove("model")
        self._agent_setting = str(st.value("agent", "claude") or "claude")
        if self._agent_setting not in agents.AGENTS:
            self._agent_setting = "claude"
        self._chat_agent = None    # agent of the open chat (a chat always continues with its own agent)
        self._lang_setting = str(st.value("language", "auto") or "auto")
        self._font_setting = str(st.value("font", "onest") or "onest")
        self._resolved = {m: str(st.value("resolved/" + m, "") or "") for m in agents.ClaudeAgent.MODELS}
        self._run_started = 0.0
        self._last_error = ""
        self._states = {}          # agent id -> agents.MISSING / LOGGED_OUT / READY (absent = not checked yet)
        self._setup = None         # the install / sign-in card: {"agent", "kind", "busy", "url", "log", "error"}
        self._setup_proc = None
        self._setup_out = ""
        self._pending = None       # (prompt, images, agent id) to send once setup is done
        self._statesReady.connect(self._on_states, Qt.QueuedConnection)
        self.refreshAgents()
        self._tr = i18n.table(i18n.resolve(self._lang_setting))
        # chat history
        self._chat_id = None
        self._chat_created = 0
        self._chat_title = None    # custom (renamed) title, or None = automatic
        self._msgs = []            # [{role, text, image}] of the current chat, as shown
        self._live_idx = -1
        self._chat_model = ChatListModel(self)
        self._load_index()

    def t(self, key):
        return self._tr.get(key, key)

    # ------------------------------------------------------------ settings / i18n
    settingsChanged = Signal()

    def _get_tr(self):
        return self._tr

    tr = Property("QVariantMap", _get_tr, notify=settingsChanged)

    def _get_lang_setting(self):
        return self._lang_setting

    language = Property(str, _get_lang_setting, notify=settingsChanged)

    def _get_languages(self):
        return [{"id": "auto", "label": self.t("lang_auto")}] + \
               [{"id": k, "label": v} for k, v in i18n.NAMES.items()]

    languages = Property("QVariantList", _get_languages, notify=settingsChanged)

    @Slot(str)
    def setLanguage(self, code):
        self._lang_setting = code if code in i18n.S else "auto"
        _settings().setValue("language", self._lang_setting)
        self._tr = i18n.table(i18n.resolve(self._lang_setting))
        self.settingsChanged.emit()
        self.modelChanged.emit()
        self._chat_model.refresh()

    def _get_font_setting(self):
        return self._font_setting

    font = Property(str, _get_font_setting, notify=settingsChanged)

    def _get_font_family(self):
        if not _font_families:
            load_fonts()
        return _font_families.get(self._font_setting) or _font_families.get("system", "")

    fontFamily = Property(str, _get_font_family, notify=settingsChanged)

    def _get_fonts(self):
        return [{"id": "onest", "label": "Onest", "family": _font_families.get("onest", "")},
                {"id": "inter", "label": "Inter", "family": _font_families.get("inter", "")},
                {"id": "system", "label": self.t("font_system"), "family": _font_families.get("system", "")}]

    fonts = Property("QVariantList", _get_fonts, notify=settingsChanged)

    @Slot(str)
    def setFont(self, key):
        if key in FONTS:
            self._font_setting = key
            _settings().setValue("font", key)
            self.settingsChanged.emit()

    def _when(self, ts):
        d = datetime.date.fromtimestamp(ts)
        days = (datetime.date.today() - d).days
        loc = QtCore.QLocale(i18n.resolve(self._lang_setting))
        if days <= 0:
            return time.strftime("%H:%M", time.localtime(ts))
        if days == 1:
            return self.t("yesterday")
        qd = QtCore.QDate(d.year, d.month, d.day)
        if days < 7:
            return loc.dayName(qd.dayOfWeek(), QtCore.QLocale.ShortFormat)
        fmt = "d MMM" if d.year == datetime.date.today().year else "d MMM yyyy"
        return loc.toString(qd, fmt)

    # ------------------------------------------------------------ properties
    def _get_busy(self):
        return self._busy

    def _set_busy(self, v):
        if v != self._busy:
            self._busy = v
            self.busyChanged.emit()

    busy = Property(bool, _get_busy, notify=busyChanged)

    def _get_status(self):
        return self._status

    def _set_status(self, v, phase=""):
        if v != self._status or phase != self._phase:
            self._status = v
            self._phase = phase
            self.statusChanged.emit()

    status = Property(str, _get_status, notify=statusChanged)

    def _get_phase(self):
        return self._phase

    phase = Property(str, _get_phase, notify=statusChanged)

    @Slot(str)
    def setStatusText(self, v):
        self._set_status(v)

    def _get_attach_label(self):
        return self._attach_label

    attachmentLabel = Property(str, _get_attach_label, notify=attachmentChanged)

    # ------------------------------------------------------------ agent + model
    modelChanged = Signal()

    @property
    def _agent_id(self):
        return self._chat_agent or self._agent_setting

    @property
    def _agent(self):
        return agents.AGENTS[self._agent_id]

    def _get_agent_id(self):
        return self._agent_id

    agent = Property(str, _get_agent_id, notify=modelChanged)

    def _get_agent_setting(self):
        return self._agent_setting

    agentSetting = Property(str, _get_agent_setting, notify=modelChanged)

    def _state(self, aid):
        st = self._states.get(aid)
        if st is None:      # not checked yet: cheap guess from files on disk
            a = agents.AGENTS[aid]
            st = agents.READY if a.ready() else (agents.LOGGED_OUT if a.find() else agents.MISSING)
        return st

    def _get_agents(self):
        out = []
        for aid in agents.ORDER:
            a = agents.AGENTS[aid]
            st = self._state(aid)
            hint = {agents.MISSING: self.t("agent_missing"), agents.LOGGED_OUT: self.t("agent_login")}.get(st, "")
            action = {agents.MISSING: self.t("btn_install"), agents.LOGGED_OUT: self.t("btn_signin")}.get(st, "")
            out.append({"id": aid, "label": a.label, "ready": st == agents.READY, "state": st,
                        "hint": hint, "action": action})
        return out

    agentList = Property("QVariantList", _get_agents, notify=modelChanged)

    _statesReady = Signal(object)

    @Slot()
    def refreshAgents(self):
        """Re-check installs and sign-ins in the background (a quick `auth status` per CLI)."""
        def work():
            res = {}
            for aid in agents.ORDER:
                try:
                    res[aid] = agents.AGENTS[aid].status()
                except Exception:
                    pass
            try:
                self._statesReady.emit(res)
            except RuntimeError:
                pass        # panel was closed meanwhile
        threading.Thread(target=work, daemon=True).start()

    def _on_states(self, res):
        self._states.update(res)
        self.modelChanged.emit()

    # ------------------------------------------------------------ setup: install / sign in
    setupChanged = Signal()

    @staticmethod
    def _names(aid):
        """(program to install, account to sign in with)"""
        return ("Claude Code", "Claude") if aid == "claude" else ("Codex", "ChatGPT")

    def _get_setup(self):
        st = self._setup
        if not st:
            return {}
        prog, acct = self._names(st["agent"])
        kind, busy = st["kind"], st.get("busy")
        button = ""
        if busy == "install":
            title, text = self.t("installing") % prog, st.get("log") or ""
        elif busy == "login":
            title, text = self.t("setup_login_t") % acct, self.t("signing_in")
        elif kind == agents.MISSING:
            title, text, button = self.t("setup_missing_t") % prog, self.t("setup_missing_b") % prog, self.t("btn_install")
        elif kind == "no_node":
            title, text, button = self.t("setup_node_t"), self.t("setup_node_b"), self.t("btn_get_node")
        else:
            title, text, button = self.t("setup_login_t") % acct, self.t("setup_login_b") % acct, self.t("btn_signin")
        if st.get("error") and not busy:
            text = (text + "\n" if text else "") + self.t("setup_failed") % st["error"]
        return {"title": title, "text": text, "button": button, "busy": bool(busy),
                "url": st.get("url", "") if busy == "login" else "",
                "openPage": self.t("btn_open_page"),
                "cancel": self.t("btn_cancel") if busy else self.t("btn_later")}

    setup = Property("QVariantMap", _get_setup, notify=setupChanged)

    def _show_setup(self, aid, kind, error=""):
        self._setup = {"agent": aid, "kind": kind, "busy": None, "url": "", "log": "", "error": error}
        self._set_status("")
        self.setupChanged.emit()

    @Slot(str)
    def startSetup(self, aid):
        """From Settings: install or sign in to the given assistant right away."""
        if aid not in agents.AGENTS or (self._setup and self._setup.get("busy")):
            return
        st = agents.AGENTS[aid].status()
        self._states[aid] = st
        self.modelChanged.emit()
        if st == agents.READY:
            return
        self._show_setup(aid, st)
        self.runSetup()

    @Slot()
    def runSetup(self):
        st = self._setup
        if not st or st.get("busy"):
            return
        a = agents.AGENTS[st["agent"]]
        if st["kind"] == "no_node":
            self.openUrl(agents.CodexAgent.NODE_URL)
            st["kind"] = agents.MISSING            # next press: try installing again
            self.setupChanged.emit()
            return
        if st["kind"] == agents.MISSING:
            cmd = a.install_command()
            if cmd is None:
                st["kind"], st["error"] = "no_node", ""
                self.setupChanged.emit()
                return
            prog, args = cmd
            st["busy"] = "install"
            env = chat_panel.child_env()
        else:
            exe = a.find()
            if not exe:
                st["kind"] = agents.MISSING
                self.setupChanged.emit()
                return
            prog, args = exe, a.login_args()
            st["busy"] = "login"
            env = a.env(chat_panel.child_env())
        st.update(error="", log="", url="", cancelled=False)
        proc = QtCore.QProcess(self)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(chat_panel.WORKDIR)
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._on_setup_out)
        proc.finished.connect(self._on_setup_done)
        proc.errorOccurred.connect(self._on_setup_error)
        self._setup_proc, self._setup_out = proc, ""
        proc.start(prog, args)
        if st["busy"] == "install":
            proc.closeWriteChannel()    # sign-in keeps stdin open: Claude may ask to paste a code
        self.setupChanged.emit()

    def _on_setup_out(self):
        proc, st = self._setup_proc, self._setup
        if not proc or not st:
            return
        self._setup_out = (self._setup_out + bytes(proc.readAllStandardOutput()).decode("utf-8", "replace"))[-20000:]
        clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", self._setup_out)
        if st.get("busy") == "login" and not st.get("url"):
            m = re.search(r"https://\S+", clean)
            if m:
                st["url"] = m.group(0)
        lines = [l.strip() for l in re.split(r"[\r\n]+", clean) if l.strip()]
        st["log"] = lines[-1][:140] if lines else ""
        self.setupChanged.emit()

    def _on_setup_error(self, err):
        if err == QtCore.QProcess.FailedToStart:
            self._on_setup_done(-1, None)

    def _on_setup_done(self, code=0, status=None):
        proc, self._setup_proc = self._setup_proc, None
        if proc is None:
            return
        try:
            self._on_setup_out_final(proc)
            proc.deleteLater()
        except RuntimeError:
            pass
        st = self._setup
        if not st:
            return
        a = agents.AGENTS[st["agent"]]
        was, st["busy"] = st.get("busy"), None
        state = a.status()
        self._states[a.id] = state
        self.modelChanged.emit()
        if state == agents.READY:
            self._setup = None
            self.setupChanged.emit()
            self._set_status(self.t("setup_done") % self._names(a.id)[1])
            pend, self._pending = self._pending, None
            if pend and not self._busy and pend[2] == self._agent_id:
                self._run(pend[0], pend[1])
            return
        if was == "install" and state == agents.LOGGED_OUT and not st.get("cancelled"):
            st["kind"] = agents.LOGGED_OUT
            self.setupChanged.emit()
            self.runSetup()             # installed: go straight on to sign in
            return
        st["kind"] = state
        if not st.get("cancelled"):
            st["error"] = st.get("log") or ("exit code %s" % code)
        self.setupChanged.emit()

    def _on_setup_out_final(self, proc):
        if proc.bytesAvailable():
            self._setup_proc = proc
            self._on_setup_out()
            self._setup_proc = None

    @Slot()
    def cancelSetup(self):
        if self._setup_proc is not None:
            if self._setup:
                self._setup["cancelled"] = True
            self._setup_proc.kill()
            return
        self._setup = None
        self._pending = None
        self.setupChanged.emit()

    def _stop_after_auth(self):
        if self.proc is not None:
            self._abandon_run()
            self._live = None
            self._set_status("")
            self._save_chat()

    @Slot()
    def openSetupPage(self):
        if self._setup and self._setup.get("url"):
            self.openUrl(self._setup["url"])

    @Slot(str)
    def setAgent(self, aid):
        if aid not in agents.AGENTS or aid == self._agent_setting:
            return
        self._agent_setting = aid
        _settings().setValue("agent", aid)
        if self._msgs:
            self._reset_chat()          # a conversation can't move between agents: start a new one
        else:
            self._chat_agent = None
        self.modelChanged.emit()

    @property
    def _model(self):
        a = self._agent
        m = _settings().value("model/" + a.id, None)
        valid = [x["id"] for x in a.models(self.t, self._resolved)]
        if m is None or str(m) not in valid:
            m = a.default_model(self._resolved)
        return str(m or "")

    def _get_model(self):
        return self._model

    model = Property(str, _get_model, notify=modelChanged)

    def _label(self, model, agent=None):
        a = agent or self._agent
        for x in a.models(self.t, self._resolved):
            if x["id"] == model:
                return x["label"]
        return model.capitalize() if model else "Default"

    def _get_model_label(self):
        return self._label(self._model)

    modelLabel = Property(str, _get_model_label, notify=modelChanged)

    def _get_models(self):
        return self._agent.models(self.t, self._resolved)

    models = Property("QVariantList", _get_models, notify=modelChanged)

    @Slot(str)
    def setModel(self, m):
        if m != self._model:
            _settings().setValue("model/" + self._agent.id, m)
            self.modelChanged.emit()

    def _learn_model(self, agent, alias, model_id):
        """Claude: remember which exact version an alias resolved to ('opus' -> 'Opus 5.5')."""
        if agent.id != "claude":
            return
        label = agent.pretty_model(model_id, alias)
        if label and self._resolved.get(alias) != label:
            self._resolved[alias] = label
            _settings().setValue("resolved/" + alias, label)
            self.modelChanged.emit()

    graphChanged = Signal()

    def _get_graph(self):
        try:
            g = self.ui_mgr.getCurrentGraph() if self.ui_mgr else None
            return g.getIdentifier() if g is not None else ""
        except BaseException:  # sd.api errors are BaseException
            return ""

    graphName = Property(str, _get_graph, notify=graphChanged)

    @Slot()
    def refreshGraph(self):
        self.graphChanged.emit()

    # ------------------------------------------------------------ chat history
    def _get_chat_model(self):
        return self._chat_model

    chatModel = Property(QObject, _get_chat_model, constant=True)

    def _get_version(self):
        return VERSION

    version = Property(str, _get_version, constant=True)

    def _get_repo_url(self):
        return REPO_URL

    repoUrl = Property(str, _get_repo_url, constant=True)

    def _get_author_url(self):
        return AUTHOR_URL

    authorUrl = Property(str, _get_author_url, constant=True)

    def _load_index(self):
        """Read the small index file; rebuild it from chat files only when it's missing or stale."""
        items, index = {}, None
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                index = json.load(f)
        except Exception:
            index = None
        files = set()
        if os.path.isdir(CHAT_DIR):
            files = {fn[:-5] for fn in os.listdir(CHAT_DIR) if fn.endswith(".json") and fn != "index.json"}
        dirty = index is None
        for cid in files:
            e = (index or {}).get(cid)
            if e is None:     # chat file not in the index: read it once
                dirty = True
                try:
                    with open(os.path.join(CHAT_DIR, cid + ".json"), encoding="utf-8") as f:
                        d = json.load(f)
                    e = {"title": d.get("title") or self.t("untitled"),
                         "updated": float(d.get("updated") or 0), "custom": bool(d.get("custom_title"))}
                except Exception:
                    continue
            items[cid] = {"id": cid, "title": e.get("title") or self.t("untitled"),
                          "updated": float(e.get("updated") or 0), "custom": bool(e.get("custom"))}
        if index and set(index) - files:
            dirty = True
        self._chat_model.reset(list(items.values()))
        if dirty:
            self._write_index()

    def _write_index(self):
        try:
            os.makedirs(CHAT_DIR, exist_ok=True)
            idx = {c["id"]: {"title": c["title"], "updated": c["updated"], "custom": c.get("custom", False)}
                   for c in self._chat_model._all}
            with open(INDEX_PATH + ".tmp", "w", encoding="utf-8") as f:
                json.dump(idx, f, ensure_ascii=False)
            os.replace(INDEX_PATH + ".tmp", INDEX_PATH)
        except Exception as e:
            print("[GraphPilot] index write failed:", e)

    def _emit(self, role, text="", image=""):
        """Show a message and record it in the current chat."""
        self._msgs.append({"role": role, "text": text, "image": image})
        self.messageAppended.emit(role, text, image)

    def _auto_title(self):
        for m in self._msgs:
            if m["role"] == "user" and m["text"].strip():
                t = m["text"]
                if t.startswith("📎 ") and "\n\n" in t:
                    t = t.split("\n\n", 1)[1] or t
                t = " ".join(t.split())
                return t[:60] + ("…" if len(t) > 60 else "")
        return self.t("screenshot") if any(m["role"] == "userimage" for m in self._msgs) else self.t("untitled")

    def _save_chat(self):
        if not self._msgs:
            return
        now = time.time()
        if not self._chat_id:
            self._chat_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-%03d" % (int(now * 1000) % 1000)
            self._chat_created = now
        title = self._chat_title or self._auto_title()
        d = {"id": self._chat_id, "title": title, "custom_title": bool(self._chat_title),
             "created": self._chat_created, "updated": now, "session_id": self.session_id,
             "agent": self._agent_id, "model": self._model, "last_prompt": self._last_prompt,
             "messages": self._msgs}
        try:
            os.makedirs(CHAT_DIR, exist_ok=True)
            p = os.path.join(CHAT_DIR, self._chat_id + ".json")
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(p + ".tmp", p)
        except Exception as e:
            print("[GraphPilot] save failed:", e)
            return
        self._chat_model.upsert({"id": self._chat_id, "title": title, "updated": now,
                                 "custom": bool(self._chat_title)})
        self._write_index()

    def _abandon_run(self):
        """Kill a running reply without letting its late events leak into another chat."""
        p, self.proc = self.proc, None
        if p is not None:
            for sig in (p.readyReadStandardOutput, p.readyReadStandardError, p.finished, p.errorOccurred):
                try:
                    sig.disconnect()
                except Exception:
                    pass
            if p.state() != QtCore.QProcess.NotRunning:
                p.kill()
                p.waitForFinished(1500)
            p.deleteLater()
        self._set_busy(False)

    def _reset_chat(self):
        old = self._chat_id
        self._abandon_run()
        self._save_chat()
        self.session_id = None
        self._chat_id = None
        self._chat_created = 0
        self._chat_title = None
        self._msgs = []
        self._live = None
        self._live_idx = -1
        self._last_prompt = ""
        self._quiet_results = set()
        had_agent, self._chat_agent = self._chat_agent, None
        self.clearAttachment()
        self._clear_images()
        self.cleared.emit()
        self._set_status("")
        if self._setup and not self._setup.get("busy"):
            self._setup = None
            self.setupChanged.emit()
        self._pending = None
        if old:
            self._chat_model.refresh(old)
        if had_agent and had_agent != self._agent_setting:
            self.modelChanged.emit()

    @Slot()
    def newChat(self):
        self._reset_chat()

    @Slot(str)
    def openChat(self, cid):
        if not cid or cid == self._chat_id:
            return
        try:
            with open(os.path.join(CHAT_DIR, cid + ".json"), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            self._set_status(self.t("cant_open_chat"))
            self._load_index()
            return
        self._reset_chat()
        self._chat_id = cid
        self._chat_created = d.get("created") or 0
        self._chat_title = d.get("title") if d.get("custom_title") else None
        self.session_id = d.get("session_id")
        self._chat_agent = d.get("agent") if d.get("agent") in agents.AGENTS else "claude"
        self.modelChanged.emit()
        self._last_prompt = d.get("last_prompt") or ""
        self._msgs = list(d.get("messages") or [])
        for m in self._msgs:
            self.messageAppended.emit(m.get("role", ""), m.get("text", ""), m.get("image", ""))
        self._chat_model.refresh(cid)

    @Slot(str, str)
    def renameChat(self, cid, title):
        title = " ".join((title or "").split())[:120]
        entry = self._chat_model.get(cid)
        if entry is None or not title or title == entry["title"]:
            return
        if cid == self._chat_id:
            self._chat_title = title
        p = os.path.join(CHAT_DIR, cid + ".json")
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            d["title"], d["custom_title"] = title, True
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(p + ".tmp", p)
        except Exception as e:
            print("[GraphPilot] rename failed:", e)
            return
        entry["title"], entry["custom"] = title, True
        self._chat_model.refresh(cid)
        self._write_index()

    @Slot(str)
    def deleteChat(self, cid):
        p = os.path.join(CHAT_DIR, cid + ".json")
        try:
            with open(p, encoding="utf-8") as f:
                msgs = json.load(f).get("messages") or []
        except Exception:
            msgs = []
        if cid == self._chat_id:
            self._msgs = []            # don't re-save it on reset
            self._reset_chat()
        for m in msgs:   # images that belong only to this chat
            ip = QUrl(m.get("image") or "").toLocalFile()
            if ip and os.path.normcase(os.path.dirname(ip)) == os.path.normcase(IMG_DIR):
                try:
                    os.remove(ip)
                except Exception:
                    pass
        try:
            os.remove(p)
        except Exception:
            pass
        self._chat_model.remove(cid)
        self._write_index()

    # ------------------------------------------------------------ images
    imagesChanged = Signal()

    def _get_images(self):
        return [QUrl.fromLocalFile(p).toString() for p in self._images]

    images = Property("QVariantList", _get_images, notify=imagesChanged)

    def _new_img_path(self, ext="png"):
        os.makedirs(IMG_DIR, exist_ok=True)
        return os.path.join(IMG_DIR, "shot_%d.%s" % (int(time.time() * 1000), ext))

    def _add_qimage(self, img):
        if img is None or img.isNull():
            return False
        if len(self._images) >= MAX_IMAGES:
            self._set_status(self.t("max_images") % MAX_IMAGES)
            return False
        p = self._new_img_path()
        if not img.save(p, "PNG"):
            return False
        self._images.append(p)
        self.imagesChanged.emit()
        return True

    @Slot(result=bool)
    def pasteImage(self):
        """Ctrl+V: attach the clipboard image (or copied image files). False = let text paste happen."""
        md = QtGui.QGuiApplication.clipboard().mimeData()
        if md is None:
            return False
        if md.hasImage():
            return self._add_qimage(QtGui.QImage(md.imageData()))
        if md.hasUrls():
            files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            files = [f for f in files if os.path.splitext(f)[1].lower() in IMG_EXTS]
            if files:
                self._add_files(files)
                return True
        return False

    def _add_files(self, files):
        added = False
        for f in files:
            if os.path.splitext(f)[1].lower() in IMG_EXTS and os.path.isfile(f):
                added = self._add_qimage(QtGui.QImage(f)) or added
        if not added and files:
            self._set_status(self.t("cant_open_image"))
        return added

    @Slot("QVariantList")
    def addFiles(self, urls):
        self._add_files([QUrl(str(u)).toLocalFile() for u in urls])

    @Slot()
    def pickImages(self):
        parent = self.ui_mgr.getMainWindow() if self.ui_mgr else None
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            parent, self.t("pick_images"), os.path.expanduser("~"),
            self.t("images_filter") + " (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tga *.tif *.tiff)")
        self._add_files(files)

    @Slot()
    def grabDesigner(self):
        """Screenshot of the Designer main window (a floating chat window is hidden for the shot)."""
        mw = self.ui_mgr.getMainWindow() if self.ui_mgr else None
        if mw is None:
            return
        own = self.parent()
        while own is not None and not isinstance(own, QtWidgets.QDockWidget):
            own = own.parent()
        floating = own is not None and own.isFloating() and own.isVisible()
        if floating:
            own.hide()

        def shoot():
            try:
                screen = mw.screen() or QtGui.QGuiApplication.primaryScreen()
                geo = mw.frameGeometry()
                pix = screen.grabWindow(0, geo.x() - screen.geometry().x(), geo.y() - screen.geometry().y(),
                                        geo.width(), geo.height())
                self._add_qimage(pix.toImage())
            finally:
                if floating:
                    own.show()
                    own.raise_()

        QtCore.QTimer.singleShot(250 if floating else 0, shoot)

    @Slot(int)
    def removeImage(self, i):
        if 0 <= i < len(self._images):
            self._images.pop(i)
            self.imagesChanged.emit()

    def _clear_images(self):
        if self._images:
            self._images = []
            self.imagesChanged.emit()

    # ------------------------------------------------------------ slots
    @Slot()
    def attachSelection(self):
        try:
            nodes = self.ui_mgr.getCurrentGraphSelectedNodes() if self.ui_mgr else None
            g = self.ui_mgr.getCurrentGraph() if self.ui_mgr else None
        except BaseException:  # sd.api errors are BaseException
            nodes, g = None, None
        if not nodes or len(nodes) == 0:
            self._set_status(self.t("nothing_selected"))
            return
        items = []
        for n in nodes:
            d = n.getDefinition()
            res = n.getReferencedResource()
            label = res.getIdentifier() if res is not None else d.getLabel()
            items.append("%s (%s, id=%s)" % (label, d.getId(), n.getIdentifier()))
        gname = g.getIdentifier() if g is not None else "?"
        self._attach = "[Selected nodes in graph %s: %s]\n" % (gname, "; ".join(items))
        self._attach_label = self.t("nodes_selected") % len(items) if len(items) > 1 else items[0].split(" (")[0]
        self._attach_nodes = (g.getIdentifier() if g is not None else None, [n.getIdentifier() for n in nodes])
        self.attachmentChanged.emit()

    @Slot()
    def clearAttachment(self):
        self._attach = ""
        self._attach_label = ""
        self._attach_nodes = None
        self.attachmentChanged.emit()

    @Slot()
    def focusAttachment(self, _retry=0):
        """Node chip clicked: show those nodes in the graph view (open the graph, fit, select)."""
        if not self._attach_nodes:
            return
        from . import helpers
        gid, ids = self._attach_nodes
        try:
            r = helpers.focus_nodes(ids, gid)
        except BaseException as e:   # graph closed / renamed
            print("[GraphPilot] focus failed:", e)
            r = {"found": 0}
        if not r.get("found"):
            self._set_status(self.t("nodes_gone"))
        elif r.get("pending") and _retry < 5:   # graph is being opened: wait for its view
            QtCore.QTimer.singleShot(250, lambda: self.focusAttachment(_retry + 1))

    @Slot(str)
    def copyText(self, text):
        QtGui.QGuiApplication.clipboard().setText(text)

    @Slot(str)
    def openUrl(self, url):
        QtGui.QDesktopServices.openUrl(QUrl(url))

    @Slot()
    def stop(self):
        if self.proc and self.proc.state() != QtCore.QProcess.NotRunning:
            self.proc.kill()

    @Slot(str)
    def send(self, text):
        text = (text or "").strip()
        if (not text and not self._images) or self._busy:
            return
        for p in self._images:
            self._emit("userimage", "", QUrl.fromLocalFile(p).toString())
        shown = text
        if self._attach_label:
            shown = ("📎 " + self._attach_label + "\n\n" + text).strip()
        if shown:
            self._emit("user", shown, "")
        prompt = self._attach + (text or self.t("look_at_images"))
        images = list(self._images)
        self.clearAttachment()
        self._clear_images()
        if self._chat_agent is None:
            self._chat_agent = self._agent_setting      # the chat is now bound to this agent
        self._last_prompt = prompt
        self._last_images = images
        self._save_chat()
        state = self._states.get(self._agent_id)
        if state != agents.READY:
            state = self._agent.status()                # ~0.2 s
            self._states[self._agent_id] = state
        if state != agents.READY:
            self._pending = (prompt, images, self._agent_id)
            self._show_setup(self._agent_id, state)
            self.modelChanged.emit()
            return
        self._run(prompt, images)

    @Slot()
    def retry(self):
        if self._last_prompt and not self._busy:
            self._run(self._last_prompt, getattr(self, "_last_images", []))

    def _run(self, prompt, images=()):
        self.graphChanged.emit()
        agent = self._agent
        self._run_agent, self._run_model = agent, self._model
        self._session_before_run = self.session_id
        exe = agent.find()
        if not exe:
            self._states[agent.id] = agents.MISSING
            self._pending = (prompt, list(images), agent.id)
            self._show_setup(agent.id, agents.MISSING)
            return
        args, stdin_text = agent.build(prompt, self._run_model, self.session_id,
                                       [p for p in images if os.path.isfile(p)])
        self.proc = QtCore.QProcess(self)
        self.proc.setWorkingDirectory(chat_panel.WORKDIR)
        self.proc.setProcessEnvironment(agent.env(chat_panel.child_env()))
        self.proc.readyReadStandardOutput.connect(self._on_stdout)
        self.proc.readyReadStandardError.connect(self._on_stderr)
        self.proc.finished.connect(self._on_finished)
        self.proc.errorOccurred.connect(self._on_error)
        self._buf = b""
        self._live = None
        self._stderr = ""
        self._last_error = ""
        self._run_started = time.time()
        self.proc.start(exe, args)
        if stdin_text is not None:
            self.proc.write(stdin_text.encode("utf-8"))
        self.proc.closeWriteChannel()
        self._set_busy(True)
        self._set_status(self.t("thinking"), "thinking")

    # ------------------------------------------------------------ process io
    def _on_error(self, err):
        if err == QtCore.QProcess.FailedToStart:
            agent = getattr(self, "_run_agent", self._agent)
            self._emit("error", self.t("cant_start") if agent.id == "claude" else self.t("codex_missing"))

    def _on_stderr(self):
        self._stderr += bytes(self.proc.readAllStandardError()).decode("utf-8", "replace")
        self._stderr = self._stderr[-20000:]

    def _on_finished(self, code, status):
        self._on_stdout()
        self._live = None
        self._set_busy(False)
        if status == QtCore.QProcess.CrashExit and self._phase:
            self._set_status(self.t("stopped"))
        elif code != 0 and self._stderr.strip() and not self._last_error:
            self._emit("error", self._stderr.strip()[-600:])
        if self._phase in ("thinking", "tool", "writing"):
            self._set_status("")
        self._save_chat()

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
            try:
                for e in self._run_agent.parse(ev):
                    self._handle(e)
            except Exception as e:
                print("[GraphPilot] event error:", e)

    def _close_live(self):
        self._live = None

    def _error(self, text):
        text = (text or "").strip()
        if text and text != self._last_error:
            self._last_error = text
            self._emit("error", text)

    def _handle(self, e):
        """Normalized agent events (see agents.py)."""
        t = e["t"]
        if t == "session":
            self.session_id = e["id"]
        elif t == "model":
            self._learn_model(self._run_agent, self._run_model, e["id"])
        elif t == "delta":
            if self._live is None:
                self._live = e["text"]
                self._emit("assistant", pretty_md(self._live))
                self._live_idx = len(self._msgs) - 1
            else:
                self._live += e["text"]
                md = pretty_md(self._live)
                if 0 <= self._live_idx < len(self._msgs):
                    self._msgs[self._live_idx]["text"] = md
                self.lastTextUpdated.emit(md)
            self._set_status(self.t("writing"), "writing")
        elif t == "text":
            if self._live is None:
                self._emit("assistant", pretty_md(e["text"]))
            self._close_live()
        elif t == "shot":
            self._close_live()
            self._quiet_results.add(e.get("id"))     # don't echo the user's own screenshot back
            self._emit("tool", self.t("viewing_shot_step"))
            self._set_status(self.t("viewing_shot"), "tool")
        elif t == "thinking":
            self._set_status(self.t("thinking"), "thinking")
        elif t == "tool":
            self._close_live()
            self._emit("tool", self._tool_label(e["name"], e.get("input") or {}))
            self._set_status("⚙ " + e["name"], "tool")
        elif t == "result":
            if e.get("id") not in self._quiet_results:
                for data in e.get("images") or []:
                    os.makedirs(IMG_DIR, exist_ok=True)
                    p = os.path.join(IMG_DIR, "render_%d.png" % int(time.time() * 1000))
                    with open(p, "wb") as f:
                        f.write(base64.b64decode(data))
                    self._emit("image", "", QUrl.fromLocalFile(p).toString())
            if self._phase == "tool":
                self._set_status(self.t("thinking"), "thinking")
        elif t == "error":
            self._error(e["text"])
        elif t == "auth":
            agent = self._run_agent
            self._last_error = "auth"                  # no raw stderr dump at exit
            self.session_id = getattr(self, "_session_before_run", self.session_id)   # the failed run's session is empty
            self._states[agent.id] = agents.LOGGED_OUT
            self._pending = (self._last_prompt, list(getattr(self, "_last_images", [])), agent.id)
            self._show_setup(agent.id, agents.LOGGED_OUT)
            self.modelChanged.emit()
            QtCore.QTimer.singleShot(0, self._stop_after_auth)   # no point letting it retry for 30 s
        elif t == "retrying":
            self._set_status(self.t("reconnecting"), "thinking")
        elif t == "done":
            if e.get("error"):
                self._error(e["error"])
            agent = self._run_agent
            if agent.id == "codex":
                self.modelChanged.emit()               # Codex's model list may have just been fetched
            if self._setup:
                return
            if agent.id == "codex" and self.session_id and not self._run_model:
                self._run_model = agent.model_of_session(self.session_id) or ""
            secs = int(round(time.time() - self._run_started)) if self._run_started else 0
            took = (self.t("min_sec") % (secs // 60, secs % 60)) if secs >= 60 else (self.t("sec") % secs if secs else "")
            model = self._label(self._run_model, agent) if self._run_model else agent.label
            self._set_status(" · ".join(p for p in (model, took) if p))

    @staticmethod
    def _tool_label(name, inp):
        detail = ""
        for k in ("definition", "library", "node_id", "name", "path", "filter"):
            if inp.get(k):
                detail = str(inp[k])
                break
        if name == "sd_execute_python":
            detail = "python"
        return name + (" · " + detail if detail and detail != "python" else "")


_keep = []


def create_dock(ui_mgr, dock_id="graphpilot", title="GraphPilot"):
    from PySide6.QtQuickWidgets import QQuickWidget

    load_fonts()
    _migrate_legacy()
    backend = ChatBackend(ui_mgr)
    view = QQuickWidget()
    view.setResizeMode(QQuickWidget.SizeRootObjectToView)
    view.rootContext().setContextProperty("backend", backend)
    view.setClearColor(QtGui.QColor("#1e1e20"))
    qml_path = os.path.join(HERE, "chat.qml")
    url = QUrl.fromLocalFile(qml_path)
    url.setQuery("v=%d" % int(os.path.getmtime(qml_path)))  # bust Qt's process-wide QML cache on hot reload
    view.setSource(url)
    if view.status() == QQuickWidget.Error:
        errs = "\n".join(e.toString() for e in view.errors())
        view.deleteLater()
        raise RuntimeError("QML failed:\n" + errs)

    dock = ui_mgr.newDockWidget(dock_id, title)
    backend.setParent(dock)
    lay = dock.layout() or QtWidgets.QVBoxLayout(dock)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(view)
    _keep.append((dock, backend, view))
    return dock, backend, view
