# Changelog

## Unreleased

- Faster mouse-wheel scrolling in the chat and the chat list (about 112 px per notch, with a short glide).
- Renders the assistant makes to check its own work are no longer dumped into the chat. It shows an image only for a final result or when you ask to see something.
- Images in the chat now really have rounded corners.
- Attached nodes in a sent message are shown as the same chip as in the message box (icon instead of the 📎 emoji). Click it to show those nodes in the graph.
- Fix: dragging images into the panel did nothing (the dropped file paths were lost on the way to Python).
- Thumbnails of attached images in the message box have rounded corners too.
- Fix: a message with attached nodes could overlap the next message.
- Fix: the copy button under a reply could be covered by the next tool step.
- The Designer bridge accepts bursts of requests (several tool calls at once no longer get "connection refused").
- Library nodes can be created by their short name (`perlin_noise` finds `noise_perlin_noise`), and failed node creation / connections now explain what is available instead of a bare API error.
- Showing nodes in the graph no longer fails when the graph's tab was closed and reopened.

## 1.2.1 — 2026-11-24

- Fix: the selected-nodes chip now shows up on its own (before, it only appeared together with a screenshot).
- Click the selected-nodes chip to show those nodes in the graph: the view opens the graph if needed, fits the nodes and selects them.
- **Ctrl+Shift+A** anywhere in Designer attaches the selected nodes and puts the cursor in the message box.

## 1.2.0 — 2026-11-24

- Settings: version, author and links to the GitHub repository and author profile.
- Install and sign in from the panel: if Claude Code / Codex is missing or not signed in, a card offers **Install** (official installer) or **Sign in** (opens the browser), then sends your message.
- Sign-in state is checked before sending, so no more walls of errors: Codex's repeated "401 Unauthorized" retries and Claude's doubled "Not logged in" message are gone.
- Settings shows "not installed" / "not signed in" with an Install / Sign in action.

## 1.1.1 — 2026-11-24

- Security: the local Designer bridge now requires a per-session random token (stored in `bridge.json` in the GraphPilot data folder). Other users and programs without access to your profile can no longer run code in Designer.
- Library nodes: the library package opened to place a node is closed again, so packages no longer pile up in the Explorer.
- README: Windows is the supported platform; macOS is untested.
- New GraphPilot logo (panel welcome screen and README).
- Fallback panel (used only if the main panel fails to load) is now in English and works with both assistants.

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
