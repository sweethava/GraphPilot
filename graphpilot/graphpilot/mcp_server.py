"""MCP stdio server: Claude Code <-> Substance 3D Designer.

Standalone script (stdlib only). Launched by the chat panel through `claude --mcp-config`
with Designer's bundled Python, and talks to the plugin's TCP bridge (127.0.0.1:9881).
Not imported by the plugin itself.
"""
import base64
import itertools
import json
import os
import socket
import sys

HOST = "127.0.0.1"
PORT = int(os.environ.get("SD_BRIDGE_PORT") or 9881)
_seq = itertools.count(1)


def sd_request(payload, timeout=300):
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as s:
            s.sendall((json.dumps(dict(payload, id=next(_seq))) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except socket.timeout:
        raise RuntimeError("Timeout talking to Designer")
    except OSError as e:
        raise RuntimeError("Cannot reach the Substance Designer bridge on %s:%d (%s). "
                           "Is Designer running with the GraphPilot plugin enabled?" % (HOST, PORT, e))


def call(fn, args):
    return sd_request({"cmd": "call", "fn": fn, "args": args})


def S(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


def s(d=""):
    return {"type": "string", "description": d}


def n(d=""):
    return {"type": "number", "description": d}


GRAPH = s("Graph identifier (default: graph currently open in Designer)")


def _render(a):
    r = call("render_node", a)
    p = ((r.get("result") or {}) if r.get("ok") else {}).get("path") or ""
    if p.lower().endswith(".png") and os.path.exists(p):
        with open(p, "rb") as f:
            r["image"] = base64.b64encode(f.read()).decode("ascii")
    return r


TOOLS = [
    ("sd_status", "Designer version, currently open graph, loaded user packages and their graphs.",
     S({}), lambda a: call("status", {})),
    ("sd_execute_python",
     "Run arbitrary Python inside Substance Designer (main thread). Preloaded: sd, app, pkg_mgr, ui_mgr, "
     "H (helpers module: graph(), node(), make_value(), ...), sdbasetypes (float2, ColorRGBA...), "
     "SDPropertyCategory. Namespace persists between calls. The value of the last expression or a variable "
     "named `result` is returned; print() output is returned too.",
     S({"code": s("Python source")}, ["code"]), lambda a: sd_request({"cmd": "exec", "code": a["code"]})),
    ("sd_get_graph", "List nodes (id, definition, position, outputs, instance url) and connections of a graph.",
     S({"graph_id": GRAPH}), lambda a: call("graph_info", a)),
    ("sd_get_node", "Inputs, parameters (with current values and types) and outputs of a node.",
     S({"node_id": s("Node id"), "graph_id": GRAPH}, ["node_id"]), lambda a: call("node_info", a)),
    ("sd_list_node_definitions",
     "List atomic node definition ids available in the graph (e.g. sbs::compositing::blend).",
     S({"filter": s("substring filter"), "graph_id": GRAPH}), lambda a: call("node_definitions", a)),
    ("sd_list_library",
     "List packages of the default Designer library (e.g. tile_generator, perlin_noise, cells_1...). "
     "Use names with sd_create_node `library`.",
     S({"filter": s("substring filter")}), lambda a: call("list_library", a)),
    ("sd_create_node",
     "Create a node. Either `definition` (atomic, e.g. 'blend', 'uniform', 'levels', 'normal', 'output', or full "
     "'sbs::compositing::blend') or `library` (library package name like 'tile_generator', optional "
     "`library_graph`). Optional params {id: value}; vectors/colors as arrays, enums as int or {enum:'id'}.",
     S({"definition": s("atomic definition id"), "library": s("library package name or .sbs path"),
        "library_graph": s("graph inside the package"), "x": n("x"), "y": n("y"),
        "params": {"type": "object", "description": "parameter values"}, "graph_id": GRAPH}),
     lambda a: call("create_node", a)),
    ("sd_set_params", "Set node input parameters: {param_id: value}.",
     S({"node_id": s("Node id"), "params": {"type": "object"}, "graph_id": GRAPH}, ["node_id", "params"]),
     lambda a: call("set_params", a)),
    ("sd_connect",
     "Connect from_node's output (default: first output) to to_node's input (default 'input1'; blend uses "
     "'source'/'destination'/'opacity', output node uses 'inputNodeOutput').",
     S({"from_node": s(), "to_node": s(), "to_input": s(), "from_output": s(), "graph_id": GRAPH},
       ["from_node", "to_node"]), lambda a: call("connect", a)),
    ("sd_disconnect", "Remove connections on a node input.",
     S({"node_id": s(), "input_id": s(), "graph_id": GRAPH}, ["node_id", "input_id"]),
     lambda a: call("disconnect", a)),
    ("sd_delete_nodes", "Delete nodes by id.",
     S({"node_ids": {"type": "array", "items": {"type": "string"}}, "graph_id": GRAPH}, ["node_ids"]),
     lambda a: call("delete_nodes", a)),
    ("sd_move_node", "Set node position.",
     S({"node_id": s(), "x": n(), "y": n(), "graph_id": GRAPH}, ["node_id", "x", "y"]),
     lambda a: call("move_node", a)),
    ("sd_new_graph", "Create a new Substance compositing graph (in a new or existing package) and open it.",
     S({"name": s("graph identifier"), "package_path": s("optional .sbs path to create/add to")}),
     lambda a: call("new_graph", a)),
    ("sd_open_package", "Open an .sbs file and its graph in Designer.",
     S({"path": s(".sbs path"), "graph_id": s("graph to open")}, ["path"]), lambda a: call("open_package", a)),
    ("sd_save_package", "Save the package containing the graph (optionally Save As path).",
     S({"path": s("optional .sbs path"), "graph_id": GRAPH}), lambda a: call("save_package", a)),
    ("sd_render_node",
     "Compute the graph and return a node output as an image (so you can see it). "
     "Optionally keep a file at `path` (png/tga/exr...).",
     S({"node_id": s(), "output": s("output id (default first)"), "path": s("save path"),
        "max_size": n("downscale preview to this many px (default 1024)"), "graph_id": GRAPH}, ["node_id"]),
     _render),
]
_BY_NAME = {t[0]: t for t in TOOLS}

INSTRUCTIONS = ("Controls a running Adobe Substance 3D Designer. Start with sd_status / sd_get_graph. "
                "Use sd_render_node to look at results. Atomic node ids: sbs::compositing::<name>. "
                "For anything not covered, use sd_execute_python with the Substance Designer Python API "
                "(its documentation is in the Designer install folder: resources/documentation/pythonapi).")


def to_content(r):
    content = []
    if r.get("image"):
        content.append({"type": "image", "data": r["image"], "mimeType": "image/png"})
    rest = {k: v for k, v in r.items() if k not in ("image", "id")}
    if not rest.get("stdout"):
        rest.pop("stdout", None)
    body = (rest if rest.get("stdout") else rest.get("result")) if rest.get("ok") else rest
    content.append({"type": "text", "text": json.dumps(body, indent=1, ensure_ascii=False, default=str)})
    return {"content": content, "isError": r.get("ok") is False}


def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return  # notification
    try:
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "substance-designer", "version": "1.0.0"},
                      "instructions": INSTRUCTIONS}
        elif method == "tools/list":
            result = {"tools": [{"name": t[0], "description": t[1], "inputSchema": t[2]} for t in TOOLS]}
        elif method == "tools/call":
            t = _BY_NAME.get(params.get("name"))
            if t is None:
                raise ValueError("Unknown tool %s" % params.get("name"))
            try:
                result = to_content(t[3](params.get("arguments") or {}))
            except Exception as e:
                result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        elif method == "ping":
            result = {}
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found: %s" % method}})
            return
        send({"jsonrpc": "2.0", "id": mid, "result": result})
    except Exception as e:
        send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}})


def main():
    # MCP uses UTF-8 newline-delimited JSON on stdio
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        handle(msg)


if __name__ == "__main__":
    main()
