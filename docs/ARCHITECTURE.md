# GraphPilot architecture

This document is for contributors (and for AI coding sessions picking the project up cold). It explains how the
pieces fit together, why they are built the way they are, and where to change things when adding a feature.

## The big picture

```
┌──────────────────── Substance 3D Designer process ────────────────────┐
│                                                                        │
│  __init__.py  initializeSDPlugin()                                     │
│   ├─ _Server: TCP bridge 127.0.0.1:9881  ──► runs requests on the      │
│   │           (token-protected, JSON lines)   Qt main thread           │
│   │                                           └─ helpers.py (SD API)   │
│   └─ chat_qml.create_dock()                                            │
│        ChatBackend (Python, QObject)  ◄──►  chat.qml (UI)              │
│          │                                                             │
└──────────┼─────────────────────────────────────────────────────────────┘
           │ QProcess (one per reply)
           ▼
   claude -p … --output-format stream-json      or      codex exec … --json -
           │  (the assistant CLI, signed in with the user's subscription)
           │ starts as its MCP server (stdio):
           ▼
   mcp_server.py  (Designer's bundled python.exe -I, stdlib only)
           │ TCP + token from %APPDATA%/GraphPilot/bridge.json
           └────────────────────────────► back into the bridge above
```

Three separate things talk to each other:

1. **The plugin** (inside Designer). It owns the SD API, the bridge server and the panel.
2. **The assistant CLI** (Claude Code or Codex), a child process started per reply. GraphPilot never calls an
   LLM API itself, so the user's own subscription and sign-in are used, and there are no API keys.
3. **The MCP server**, a child of the CLI. It turns MCP tool calls (`sd_*`) into bridge requests.

## Repository layout

```
graphpilot/                    the plugin folder (goes into …/python/sduserplugins/)
  pluginInfo.json              name, version (single source of truth for the version), author
  graphpilot/
    __init__.py                plugin entry points + TCP bridge
    helpers.py                 graph operations on the SD API (what the tools actually do)
    mcp_server.py              MCP stdio server, standalone script, stdlib only
    agents.py                  Claude Code / Codex adapters: find, status, install, sign in, build args, parse events
    chat_qml.py                ChatBackend: chat state, history, settings, setup flow, process I/O
    chat.qml                   the whole UI (one file)
    chat_panel.py              shared launch settings (system prompt, MCP config, python lookup) + widget fallback panel
    i18n.py                    UI strings, 10 languages
    icons/*.svg, icons/logo.png
    fonts/                     Onest, Inter (OFL)
tools/build.py                 → dist/GraphPilot-<version>.zip
tools/dev_install.ps1          junction sduserplugins/graphpilot → repo (dev setup)
docs/                          logo, README screenshots, this file
```

## 1. Plugin entry and the bridge (`__init__.py`)

- Designer calls `initializeSDPlugin()` on start and `uninitializeSDPlugin()` on exit.
- `_Server` listens on `127.0.0.1:9881` in a daemon thread. Each connection is handled in its own thread, and
  each request is dispatched to the **Qt main thread** through a queued signal (`_Dispatcher`), because the SD API
  is not thread-safe. The worker waits up to `timeout` (default 300 s).
- **Auth.** On every start, a random token (`secrets.token_urlsafe(32)`) is generated and written with the port
  and pid to `<DATA_DIR>/bridge.json` (owner-only). Every request must carry it; it is compared with
  `hmac.compare_digest`. On exit the file is removed if it is still ours.
- **Protocol.** Newline-delimited JSON.
  - `{"cmd":"exec","code":…}` runs Python in a persistent namespace (`sd`, `app`, `pkg_mgr`, `ui_mgr`,
    `H` = helpers, sdbasetypes…). The value of the last expression or a variable `result` is returned, together
    with captured stdout.
  - `{"cmd":"call","fn":"graph_info","args":{…}}` calls a function in `helpers.py`.
  - `{"cmd":"ping"}`.
- Results go through `helpers.to_py()` to become JSON-safe.
- Note: SD's `APIException` derives from `BaseException`, so the bridge catches `BaseException`.
- The panel: `chat_qml.create_dock()`; if QML fails to load, it falls back to `chat_panel.create_dock()`.

`DATA_DIR` is `%APPDATA%/GraphPilot` on Windows (macOS / XDG paths exist but are untested).

## 2. Graph operations (`helpers.py`)

Plain functions that the bridge's `call` command exposes and the MCP tools use:
`status, graph_info, node_info, node_definitions, list_library, create_node, set_params, connect, disconnect,
delete_nodes, move_node, new_graph, open_package, save_package, render_node`.

- `graph(graph_id=None)` resolves "the current graph" (the one open in the editor, else the last used one).
- `make_value(type_id, v)` converts JSON values (numbers, arrays, `{enum: id}`) into SD values.
- `create_node(library=…)` instantiates a node from the default library (e.g. `tile_generator`). It loads the
  library package, creates the instance, then **unloads the library package**; the instance keeps working
  because Designer holds it as a dependency. Library files have names like `noise_perlin_noise.sbs`.
- `render_node` computes the graph and saves a PNG. `graph.compute()` only refreshes graph *output* nodes, so it
  attaches a temporary Output node to the requested output, reads it, and removes it.
- Opening a resource in the editor is `app.getUIMgr().openResourceInEditor`, not the QtForPython UI manager.

**To add a tool:** write the function in `helpers.py`, then add an entry to `TOOLS` in `mcp_server.py`
(name, description, JSON schema, handler `lambda a: call("your_fn", a)`). Both CLIs pick it up automatically.

## 3. MCP server (`mcp_server.py`)

- A standalone script, **stdlib only**, not imported by the plugin. The CLI starts it with Designer's bundled
  Python (`plugins/pythonsdk/python.exe -I`), found by `chat_panel._find_python()`, so users need no Python or Node.
- It speaks MCP JSON-RPC over stdio (`initialize`, `tools/list`, `tools/call`, `ping`).
- `_bridge()` re-reads `bridge.json` on **every** call (the token changes each Designer start); the env vars
  `SD_BRIDGE_PORT` / `SD_BRIDGE_TOKEN` override it.
- `sd_render_node` returns the PNG as an MCP image block, so the model can actually see the render. Its `show` flag (default false) decides whether the panel also shows the image to the user; the server drops it before calling the bridge.
- The server is registered per run on the command line (no `claude mcp add` / no edits to the user's config):
  Claude gets `--mcp-config <json> --strict-mcp-config`; Codex gets `-c mcp_servers.sd.*`.

## 4. Agent adapters (`agents.py`)

Each assistant is an adapter object with the same interface. `AGENTS = {"claude": …, "codex": …}`,
`ORDER` sets the order in Settings.

| Method | Purpose |
|---|---|
| `find()` | path of the CLI executable, or None |
| `status()` | `MISSING` / `LOGGED_OUT` / `READY` (runs `claude auth status` / `codex login status`, ~0.2 s) |
| `login_args()` | sign-in command (`auth login` / `login`); it opens the browser and also prints the URL |
| `install_command()` | `(program, args)` of the official installer, or None (Codex without Node.js) |
| `models(t, resolved)`, `default_model()` | entries for the model picker |
| `build(prompt, model, session_id, images)` | `(args, stdin_text)` for one reply |
| `env(env)` | extra environment for the child process |
| `parse(event)` | CLI JSON event → list of **normalized events** |
| `pretty_model(id, alias)` | display name of a model |

**Normalized events** (documented at the top of `agents.py`): `session, model, delta, text, tool, shot,
thinking, result, error, auth, retrying, done`. The backend only knows these, so the UI never depends on a
specific CLI's format.

### Claude Code
- Launch: `claude -p <prompt> --output-format stream-json --verbose --include-partial-messages --model <alias>
  [--resume <session>]` + MCP config + `--append-system-prompt` + `--allowedTools` (see `chat_panel.py`).
- Models are the aliases `fable / opus / sonnet / haiku`, so the newest model of each family is always used. The
  real model id comes from the `system/init` event and is remembered (`resolved/<alias>` in settings) to show
  "Opus 5.5" instead of "Opus".
- Attached screenshots: the prompt asks Claude to open the files with its Read tool; reading them is shown as
  a `shot` step, and the image is not echoed back.
- When not signed in, Claude sends an assistant message with `error: "authentication_failed"` and then an
  error result; `parse` turns that into one `auth` event.

### Codex (ChatGPT)
- On Windows the npm `codex` command is a .cmd/.ps1 shim, so `find()` locates the **native `codex.exe`** inside
  the npm package (`vendor/*/bin`), and `env()` sets the `CODEX_MANAGED_*` variables that the shim would set.
- Launch: `codex exec [resume <thread>] -i <img>… --json --skip-git-repo-check -c sandbox_mode="read-only"
  -c developer_instructions=… -c mcp_servers.sd.{command,args,default_tools_approval_mode="approve"} -m <slug> -`,
  with the prompt on **stdin**. Without `default_tools_approval_mode="approve"`, MCP calls fail in exec mode.
- Models come from `~/.codex/models_cache.json` (`visibility == "list"`, sorted by `priority`). `--json` does not
  report the model, so `model_of_session()` reads it from the session file. Codex has no text streaming in `--json`.
- Not signed in: Codex retries with `Reconnecting… n/5 (401 Unauthorized)` errors and then `turn.failed`.
  `_error()` maps the first 401 to `auth` and other reconnects to `retrying`.

**To add another assistant:** write an adapter class with the methods above, add it to `AGENTS` and `ORDER`,
add its names in `ChatBackend._names()` and strings in `i18n.py`.

## 5. Chat backend (`chat_qml.py`, `ChatBackend`)

A `QObject` exposed to QML as `backend` (context property). QML reads `Property`s and calls `Slot`s.

**A reply's life cycle**
1. `send(text)` shows the user message (and attached images), builds the prompt (selected-nodes attachment +
   text), saves the chat, checks the assistant's state; if it is not `READY`, the message is kept in
   `_pending` and the **setup card** is shown instead.
2. `_run(prompt, images)` starts a `QProcess` with `agent.build(...)`, `agent.env(child_env())`
   (Designer's `PYTHONHOME/PYTHONPATH` are removed), working directory = home folder.
3. `_on_stdout` splits JSON lines → `agent.parse` → `_handle(event)`, which updates the message list, status
   pill and phase (`thinking / tool / writing`).
4. `done` → the status pill shows "Model · time"; `_on_finished` saves the chat.

**Messages.** Everything shown goes through `_emit(role, text, image, nodes=None)` (roles: `user, userimage, assistant,
tool, image, error`). It appends to `_msgs` (saved to disk) and emits `messageAppended` for QML. Streaming text
updates the last assistant message via `lastTextUpdated`. `pretty_md()` rewrites Markdown lists because Qt's
Markdown renderer indents them badly.

**Chat history.** `DATA_DIR/chats/<id>.json` holds `{title, custom_title, created, updated, session_id, agent,
model, last_prompt, messages}`; `chats/index.json` keeps titles/dates so the list loads without reading every
chat. `ChatListModel` (a `QAbstractListModel`) backs the drawer, with search via `setFilter`. Opening a chat
replays its messages and continues the CLI session with `--resume` / `exec resume`. **A chat stays bound to the
assistant it was started with** (`_chat_agent`); the Settings choice applies to new chats.

**Switching chats while a reply runs.** `_abandon_run()` disconnects the process signals before killing it, so
late events never leak into another chat.

**Screenshots.** Ctrl+V (`pasteImage`), drag & drop (`addFiles`), the + menu (`pickImages`, `grabDesigner`).
Files are saved to `DATA_DIR/images` (kept so history thumbnails survive restarts). Max 6 per message.
Renders the AI asked to show (`show: true`) are saved there too; other tool results are not shown (`_quiet_results`).

**Node chips.** A sent message keeps its attached nodes as `nodes = {label, graph, ids}` in the chat file; QML shows a chip that calls `focusMessageNodes(index)` → `helpers.focus_nodes`. Older chats stored the chip as a "📎 label" text prefix; `_legacy_chip` / `_recover_chip_ids` convert them on open.

**Setup flow (install / sign in).**
- `_states` caches each agent's state; `refreshAgents()` re-checks in a background thread
  (`_statesReady` signal back to the main thread).
- The card is described by the `setup` property (title, text, button, busy, url…).
  - `runSetup()` starts the installer or the sign-in command as a `QProcess`.
  - `_on_setup_out` picks up the sign-in URL ("Open sign-in page") and the last log line.
  - `_on_setup_done` re-checks the state. When `READY`, it sends the `_pending` message; after an install it
    goes straight on to sign in.
- If a reply hits `auth` in the middle of a run, the run is stopped. The session id is restored to the one before
  the run (the failed run's session is empty), the message is kept as pending, and the card is shown.
- `startSetup(aid)` is the same flow started from Settings.

**Settings** live in `QSettings("GraphPilot", "GraphPilot")`: `agent`, `model/<agent>`, `language`
(`auto` or a code), `font` (`onest / inter / system`), `theme` (`graphite / designer / midnight / ember`), `resolved/<alias>`.

## 6. UI (`chat.qml`)

- **Only the base `QtQuick` module exists in Designer's Qt**, without QtQuick.Controls or Layouts. Everything
  (buttons, menus, tooltips, scrollbars) is built from `Rectangle`, `Text`, `MouseArea` and anchors.
  `pixelSize` must be an int.
- One file. Main blocks, top to bottom:
  - `palettes` + `theme` (colors, font). A palette is only `{tint, accent, accentHover, onAccent, ok}`: every
    grey role in `theme` is a neutral value passed through `root.tone()` (`Qt.tint` toward the palette's tint;
    text gets a third of it). Use `theme.<role>` for every colour; add new greys as roles, never as hex in place.
    The theme list and labels are `THEMES` in `chat_qml.py`;
  - `header`;
  - `list` (ListView of messages, with delegates `userMsg / botMsg / toolMsg / imageMsg / userImageMsg / errorMsg`);
  - welcome screen (logo + greeting);
  - `setupCard`;
  - `composer` (input, + menu, model picker, send/stop);
  - `PopupMenu`s;
  - `drop` (drag & drop);
  - `drawer` (chat history);
  - `settings` (assistant, language, font, about line);
  - `tooltip`.
- Strings: `tx.<key>` (= `backend.tr`, a map from `i18n.py`).
- Images loaded with `cache: false` where they change during development (hot reload).
- `clip` in QtQuick is rectangular, so rounded images go through `backend.thumb(url, w, h, radius)`: a cropped 2x copy with rounded corners, cached in `DATA_DIR/thumbs`.
- Mouse-wheel speed: `WheelScroll` (a button-less MouseArea over a list) scrolls ~112 px per notch with a short glide.
- `create_dock` adds `?v=<mtime>` to the QML URL, because Qt caches compiled QML per process.

## 7. Strings (`i18n.py`)

`S["en"]` is the full table; other languages override keys, and anything missing falls back to English.
Language = setting, or the OS language for `auto`. Newer key groups (`_AGENT`, `_SETUP`) are stored as
per-language tuples with an `assert` on their length. **Every new string must be added for all 10 languages.**

## 8. Fallback panel (`chat_panel.py`)

`BasicChat` is a plain-widget chat used only when QML fails. It uses the same adapters and events, but has
no history, setup card or images. The module also holds the shared launch settings: `SYSTEM_PROMPT`,
`ALLOWED_TOOLS`, `claude_base_args()`, `_find_python()`, `_find_claude()`, `child_env()`, `WORKDIR`.

## Security model

- The bridge listens on localhost only and requires the per-session token, which only the same OS user can read.
- Codex runs with `sandbox_mode="read-only"`; Claude's tools are limited by `--allowedTools`. Graph edits
  happen only through the MCP tools. `sd_execute_python` can run any Python inside Designer, which is why
  the token matters.
- No telemetry, no network calls of our own. Installers and sign-in are the vendors' official ones.

## Development workflow

- **Dev install:** run `tools/dev_install.ps1` once (with Designer closed). It makes
  `…/sduserplugins/graphpilot` a junction to the repo's `graphpilot/`, so the code in the repo is what Designer runs.
- **Apply changes:** restart Designer. Hot reload is possible: through the bridge, reload the modules
  (`importlib.reload` of `i18n`, `chat_panel`, `agents`, `chat_qml`) and create a new dock with a new id
  (dock ids can't be reused within a session).
- **Run code in Designer from outside:** connect to the bridge with the token from `bridge.json` and send `exec`.
- **Build:** `python tools/build.py` → `dist/GraphPilot-<version>.zip` (checks that all .py compile).
- **Release:**
  1. Bump `version` in `graphpilot/pluginInfo.json`.
  2. Add a `CHANGELOG.md` entry.
  3. Build.
  4. Commit and push.
  5. `gh release create v<ver> dist/GraphPilot-<ver>.zip`.
  6. Replace the file on the Gumroad product page.
- **Testing without signing out:** point the CLIs at an empty config with `CLAUDE_CONFIG_DIR` / `CODEX_HOME`
  to see the logged-out / missing paths.

## Where to put a new feature

| Feature | Files |
|---|---|
| New graph capability for the AI | `helpers.py` + `TOOLS` in `mcp_server.py` |
| Change what the AI is told | `SYSTEM_PROMPT` in `chat_panel.py` (both CLIs) |
| New assistant / CLI | new adapter in `agents.py`, `_names()` in `chat_qml.py`, strings |
| New setting | property + slot in `ChatBackend`, QSettings key, a row in the `settings` block of `chat.qml`, strings |
| New message type in the chat | `_emit` role in `chat_qml.py`, a delegate `Component` in `chat.qml` |
| Any visible text | `i18n.py`, all 10 languages |
