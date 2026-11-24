# GraphPilot: notes for AI coding sessions

GraphPilot is an AI chat panel for Adobe Substance 3D Designer 16+. It runs the user's own **Claude Code** or
**Codex (ChatGPT)** CLI, and the CLI edits the open graph through a bundled MCP server.

**Read `docs/ARCHITECTURE.md` first.** It covers how the bridge, MCP server, agent adapters, backend and QML fit
together, and where to put new features.

## Rules

- **Designer's Qt has only base `QtQuick`**, with no Controls and no Layouts. Build UI from Rectangle/Text/MouseArea
  and anchors. QML `pixelSize` must be an int.
- **Every visible string goes into `i18n.py` for all 10 languages** (en, ru, uk, de, es, fr, pt, zh, ja, ko).
- The UI talks only to normalized agent events (`agents.py`), never to a CLI's raw format.
- `mcp_server.py` must stay **stdlib only** (it runs with Designer's bundled Python, `-I`).
- SD API calls only on the Qt main thread (the bridge already does this). SD's `APIException` is a `BaseException`.
- Product name rule: no "Claude", "Substance" or "Adobe" in the product name. Keep the trademark note in README.
- Windows is the tested platform; macOS/Linux code paths exist but are untested, so don't claim they work.
- Version lives only in `graphpilot/pluginInfo.json`. Releases: bump version, CHANGELOG entry,
  `python tools/build.py`, commit, push, `gh release create v<ver> dist/GraphPilot-<ver>.zip`, and replace the
  zip on Gumroad.
- After editing plugin code, restart Designer so the running version is current (check for unsaved packages
  first). Machine-specific dev tooling is in `CLAUDE.local.md` (not committed).

## Links

- Repo: https://github.com/sweethava/GraphPilot (public, MIT, author SweetHava)
- Gumroad: https://sweethava.gumroad.com/l/graphpilot ($0+, pay what you want)
