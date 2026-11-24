# Changelog

## Unreleased

- Security: the local Designer bridge now requires a per-session random token (stored in `bridge.json` in the GraphPilot data folder). Other users and programs without access to your profile can no longer run code in Designer.
- Library nodes: the library package opened to place a node is closed again, so packages no longer pile up in the Explorer.
- README: Windows is the supported platform; macOS is untested.
- New GraphPilot logo (panel welcome screen and README).

## 1.1.0 — 2026-11-24

- **ChatGPT support** through OpenAI Codex CLI: use your ChatGPT plan instead of Claude. Pick the assistant in Settings; each chat keeps the assistant it was started with.
- Codex runs read-only (its sandbox) plus the Designer tools; attached screenshots are passed to it directly.
- Fixed: Designer API errors inside tools were hidden behind a generic error.
- Fixed: placing library nodes from packages whose first graph is a function graph.
- Chat list: side padding; renaming is cancelled by Esc or clicking away.
- The tool-steps button shows whether steps are hidden.

## 1.0.0 — 2026-11-24

First public release.

- Chat panel docked in Substance 3D Designer, powered by Claude Code (your Claude subscription or API key).
- Claude reads and edits the open graph: create/connect/delete nodes, set parameters, render node outputs, run Python.
- Attach screenshots: Ctrl+V, drag & drop, "Screenshot of Designer", image from disk, selected nodes.
- Chat history: search, rename, delete; chats resume with full context.
- Model picker (Fable / Opus / Sonnet / Haiku) that always uses the newest version of each family.
- 10 UI languages (follows the OS, switchable in Settings); fonts: Onest, Inter or system.
- No setup besides Claude Code: the MCP server ships with the plugin and runs on Designer's bundled Python.
