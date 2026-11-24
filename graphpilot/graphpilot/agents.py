"""Agent adapters: how to launch a coding-agent CLI headless and read its event stream.

Each adapter turns the CLI's own JSON events into a small set of normalized events
that the chat backend understands:

    {"t": "session", "id": str}                  conversation id to resume later
    {"t": "model", "id": str}                    exact model id the agent used
    {"t": "delta", "text": str}                  streamed text chunk
    {"t": "text", "text": str}                   a complete assistant message
    {"t": "tool", "id", "name", "input"}         a tool call started (name without server prefix)
    {"t": "shot", "id"}                          the agent is opening an attached screenshot
    {"t": "thinking"}                            internal step, nothing to show
    {"t": "result", "id", "images": [b64png]}    tool finished; images it returned
    {"t": "error", "text": str}                  an error/warning to show (the turn may go on)
    {"t": "done", "error": str|None}             turn finished
"""
import glob
import json
import os
import re
import shutil
import sys

from . import chat_panel

IS_WIN = sys.platform.startswith("win")
MCP_NAME = "substance-designer"


def _strip_prefix(name):
    for p in ("mcp__substance-designer__", "mcp__sd__"):
        if name.startswith(p):
            return name[len(p):]
    return name


# ======================================================================= Claude Code
class ClaudeAgent:
    id = "claude"
    label = "Claude"
    HIDDEN_TOOLS = {"ToolSearch"}
    MODELS = ["fable", "opus", "sonnet", "haiku"]      # aliases -> always the newest of each family

    def find(self):
        return chat_panel._find_claude()

    def ready(self):
        return bool(self.find())

    def models(self, t, resolved):
        return [{"id": m, "label": resolved.get(m) or m.capitalize(), "hint": t("hint_" + m)} for m in self.MODELS]

    def default_model(self, resolved):
        return "opus"

    def build(self, prompt, model, session_id, images):
        """-> (args, stdin_text). Claude opens attached images itself with its Read tool."""
        if images:
            prompt = ("[The user attached images (screenshots). First open each one with the Read tool "
                      "and take them into account: %s]\n" % "; ".join(images)) + prompt
        args = ["-p", prompt, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--model", model, *chat_panel.claude_base_args()]
        if session_id:
            args += ["--resume", session_id]
        return args, None

    def env(self, env):
        return env

    def parse(self, ev):
        out = []
        t = ev.get("type")
        if ev.get("session_id"):
            out.append({"t": "session", "id": ev["session_id"]})
        if t == "system" and ev.get("subtype") == "init" and ev.get("model"):
            out.append({"t": "model", "id": ev["model"]})
        elif t == "stream_event":
            e = ev.get("event", {})
            if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta":
                out.append({"t": "delta", "text": e["delta"].get("text", "")})
        elif t == "assistant":
            for block in ev.get("message", {}).get("content", []):
                bt = block.get("type")
                if bt == "text" and block.get("text"):
                    out.append({"t": "text", "text": block["text"]})
                elif bt == "tool_use":
                    name, inp = block.get("name", ""), block.get("input") or {}
                    if name == "Read" and os.path.basename(str(inp.get("file_path", ""))).startswith("shot_"):
                        out.append({"t": "shot", "id": block.get("id")})
                    elif name in self.HIDDEN_TOOLS:
                        out.append({"t": "thinking"})
                    else:
                        out.append({"t": "tool", "id": block.get("id"), "name": _strip_prefix(name), "input": inp})
        elif t == "user":
            content = ev.get("message", {}).get("content", [])
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_result":
                    imgs = []
                    for c in block.get("content") if isinstance(block.get("content"), list) else []:
                        if c.get("type") == "image" and (c.get("source") or {}).get("data"):
                            imgs.append(c["source"]["data"])
                    out.append({"t": "result", "id": block.get("tool_use_id"), "images": imgs})
        elif t == "result":
            err = str(ev.get("result") or ev.get("subtype")) if ev.get("is_error") else None
            out.append({"t": "done", "error": err})
        return out

    def pretty_model(self, model_id, alias):
        m = re.match(r"^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$", model_id or "")
        if m and m.group(1) == alias:
            return "%s %s%s" % (m.group(1).capitalize(), m.group(2), "." + m.group(3) if m.group(3) else "")
        return None


# ======================================================================= OpenAI Codex (ChatGPT plan)
class CodexAgent:
    id = "codex"
    label = "ChatGPT"

    @staticmethod
    def home():
        return os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")

    def find(self):
        """The native codex binary. On Windows the npm shim is a .cmd/.ps1 script, which we don't run
        (prompts would pass through cmd.exe), so locate the real executable inside the npm package."""
        exe = "codex.exe" if IS_WIN else "codex"
        roots = []
        if IS_WIN:
            roots.append(os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules"))
        else:
            roots += ["/opt/homebrew/lib/node_modules", "/usr/local/lib/node_modules",
                      os.path.expanduser("~/.npm-global/lib/node_modules")]
        for root in roots:
            pkg = os.path.join(root, "@openai", "codex")
            pats = [os.path.join(pkg, "node_modules", "@openai", "codex-*", "vendor", "*", "bin", exe),
                    os.path.join(root, "@openai", "codex-*", "vendor", "*", "bin", exe),
                    os.path.join(pkg, "vendor", "*", "bin", exe)]
            for pat in pats:
                hits = glob.glob(pat)
                if hits:
                    return hits[0]
        w = shutil.which("codex")
        if w and (not IS_WIN or w.lower().endswith(".exe")):
            return w
        if not IS_WIN:
            for c in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex", os.path.expanduser("~/.local/bin/codex")):
                if os.path.isfile(c):
                    return c
        return None

    def logged_in(self):
        return os.path.isfile(os.path.join(self.home(), "auth.json"))

    def ready(self):
        return bool(self.find()) and self.logged_in()

    def _cache(self):
        try:
            with open(os.path.join(self.home(), "models_cache.json"), encoding="utf-8") as f:
                ms = json.load(f).get("models") or []
        except Exception:
            return []
        ms = [m for m in ms if m.get("visibility") == "list" and m.get("slug")]
        return sorted(ms, key=lambda m: m.get("priority", 999))

    def models(self, t, resolved):
        out = []
        for m in self._cache():
            hint = (m.get("description") or "").split(".")[0]
            hint = re.sub(r"\s+(model|models)\b.*$", "", hint, flags=re.I)
            out.append({"id": m["slug"], "label": m.get("display_name") or m["slug"],
                        "hint": hint[:28] + ("…" if len(hint) > 28 else "")})
        return out or [{"id": "", "label": "Default", "hint": ""}]

    def default_model(self, resolved):
        ms = self._cache()
        return ms[0]["slug"] if ms else ""

    @staticmethod
    def _toml(v):
        return json.dumps(v, ensure_ascii=False)   # a JSON string/array is valid TOML

    def build(self, prompt, model, session_id, images):
        """-> (args, stdin_text). The prompt goes through stdin ('-'), images via -i."""
        args = ["exec"]
        if session_id:
            args += ["resume", session_id]
        for p in images:
            args += ["-i", p]
        py = chat_panel._find_python()
        args += ["--json", "--skip-git-repo-check",
                 "-c", "sandbox_mode=" + self._toml("read-only"),
                 "-c", "developer_instructions=" + self._toml(chat_panel.SYSTEM_PROMPT)]
        if py:
            args += ["-c", "mcp_servers.sd.command=" + self._toml(py),
                     "-c", "mcp_servers.sd.args=" + self._toml(["-I", chat_panel.MCP_SERVER]),
                     "-c", "mcp_servers.sd.default_tools_approval_mode=" + self._toml("approve")]
        if model:
            args += ["-m", model]
        args.append("-")
        return args, prompt

    def env(self, env):
        # what the npm launcher would set
        exe = self.find() or ""
        m = re.search(r"^(.*[\\/]@openai[\\/]codex)[\\/]", exe)
        if m:
            env.insert("CODEX_MANAGED_PACKAGE_ROOT", m.group(1))
            env.insert("CODEX_MANAGED_BY_NPM", "1")
        return env

    def parse(self, ev):
        out = []
        t = ev.get("type")
        item = ev.get("item") or {}
        it = item.get("type")
        if t == "thread.started" and ev.get("thread_id"):
            out.append({"t": "session", "id": ev["thread_id"]})
        elif t == "item.started":
            if it == "mcp_tool_call":
                out.append({"t": "tool", "id": item.get("id"), "name": _strip_prefix(item.get("tool", "")),
                            "input": item.get("arguments") or {}})
            elif it == "command_execution":
                out.append({"t": "tool", "id": item.get("id"), "name": "shell",
                            "input": {"name": str(item.get("command", ""))[:60]}})
            elif it == "web_search":
                out.append({"t": "tool", "id": item.get("id"), "name": "web_search",
                            "input": {"name": str(item.get("query", ""))[:60]}})
            elif it == "reasoning":
                out.append({"t": "thinking"})
        elif t == "item.completed":
            if it == "agent_message" and item.get("text"):
                out.append({"t": "text", "text": item["text"]})
            elif it == "mcp_tool_call":
                imgs = [c.get("data") for c in ((item.get("result") or {}).get("content") or [])
                        if c.get("type") == "image" and c.get("data")]
                out.append({"t": "result", "id": item.get("id"), "images": imgs})
            elif it == "error" and item.get("message"):
                out.append({"t": "error", "text": item["message"]})     # non-fatal; the turn goes on
        elif t == "turn.completed":
            out.append({"t": "done", "error": None})
        elif t == "turn.failed":
            out.append({"t": "done", "error": ((ev.get("error") or {}).get("message")) or "turn failed"})
        elif t == "error" and ev.get("message"):
            out.append({"t": "error", "text": ev["message"]})
        return out

    def model_of_session(self, thread_id):
        """Codex doesn't print the model in --json; read it from the session file."""
        hits = glob.glob(os.path.join(self.home(), "sessions", "*", "*", "*", "*%s*.jsonl" % thread_id))
        if not hits:
            return None
        try:
            with open(hits[0], encoding="utf-8") as f:
                for _ in range(40):
                    line = f.readline()
                    if not line:
                        break
                    m = re.search(r'"model"\s*:\s*"([^"]+)"', line)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        return None

    def pretty_model(self, model_id, alias):
        for m in self._cache():
            if m["slug"] == model_id:
                return m.get("display_name") or model_id
        return model_id or None


AGENTS = {"claude": ClaudeAgent(), "codex": CodexAgent()}
ORDER = ["claude", "codex"]
