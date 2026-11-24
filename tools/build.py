"""Build the release archive: dist/GraphPilot-<version>.zip

    python tools/build.py

Checks that every .py compiles, then zips the plugin folder (graphpilot/) together with
README, LICENSE, CHANGELOG and third-party notices. Stdlib only, Python 3.9+.
"""
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "graphpilot")
DOCS = ["README.md", "LICENSE", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md"]
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_EXT = {".pyc", ".pyo"}
REQUIRED = ["pluginInfo.json", "graphpilot/__init__.py", "graphpilot/chat.qml", "graphpilot/mcp_server.py",
            "graphpilot/fonts/Onest-Variable.ttf", "graphpilot/fonts/InterVariable.ttf"]


def plugin_files():
    for d, dirs, files in os.walk(PLUGIN):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() not in SKIP_EXT:
                yield os.path.join(d, f)


def main():
    with open(os.path.join(PLUGIN, "pluginInfo.json"), encoding="utf-8") as f:
        info = json.load(f)
    version = info["version"]

    missing = [r for r in REQUIRED if not os.path.isfile(os.path.join(PLUGIN, r))]
    if missing:
        sys.exit("missing files: %s" % ", ".join(missing))

    errors = []
    for p in plugin_files():
        if p.endswith(".py"):
            try:
                with open(p, "rb") as f:
                    compile(f.read(), p, "exec")
            except SyntaxError as e:
                errors.append(str(e))
    if errors:
        sys.exit("syntax errors:\n" + "\n".join(errors))

    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", "%s-%s.zip" % (info["name"], version))
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in plugin_files():
            z.write(p, os.path.relpath(p, ROOT).replace(os.sep, "/"))
            n += 1
        for doc in DOCS:
            z.write(os.path.join(ROOT, doc), doc)
    print("built %s (%d plugin files, %.1f MB)" % (out, n, os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
