"""High-level helpers exposed to the MCP server (and as `H` in exec code)."""
import glob
import importlib
import os
import tempfile

import sd
from sd.api.sdbasetypes import float2
from sd.api.sdproperty import SDPropertyCategory
from sd.api.sdapplication import SDApplicationPath


# ------------------------------------------------------------------ basics
def _app():
    return sd.getContext().getSDApplication()


def _pm():
    return _app().getPackageMgr()


def _ui():
    return _app().getQtForPythonUIMgr()


_VEC_ATTRS = ("x", "y", "z", "w")
_COL_ATTRS = ("r", "g", "b", "a")


def to_py(o, depth=0):
    """Convert SD objects / values into JSON-friendly python."""
    if depth > 6:
        return str(o)
    if o is None or isinstance(o, (bool, int, float, str)):
        return o
    if isinstance(o, (list, tuple)):
        return [to_py(x, depth + 1) for x in o]
    if isinstance(o, dict):
        return {str(k): to_py(v, depth + 1) for k, v in o.items()}
    cls = type(o).__name__
    if cls.startswith(("float", "int", "double", "bool")) and cls[-1] in "234":
        return [getattr(o, a) for a in _VEC_ATTRS[: int(cls[-1])]]
    if cls in ("ColorRGB", "ColorRGBA"):
        return [getattr(o, a) for a in _COL_ATTRS[: len(cls) - 5]]
    if cls == "SDValueEnum":
        try:
            return {"enum": o.getValueId(), "value": o.get()}
        except BaseException:
            return o.get()
    if cls == "SDValueArray" or cls == "SDArray":
        try:
            return [to_py(x, depth + 1) for x in o]
        except BaseException:
            return str(o)
    if cls == "SDValueStruct":
        try:
            props = o.getType().getProperties()
            return {p.getId(): to_py(o.getPropertyValue(p), depth + 1) for p in props}
        except BaseException:
            return str(o)
    if cls.startswith("SDValue") and hasattr(o, "get"):
        try:
            return to_py(o.get(), depth + 1)
        except BaseException:
            return str(o)
    if cls == "SDTexture":
        return "<SDTexture %s>" % to_py(o.getSize())
    if cls in ("SDNode", "SDSBSCompNode", "SDSBSFunctionNode", "SDSBSFxMapNode"):
        return {"node": o.getIdentifier(), "definition": o.getDefinition().getId()}
    if hasattr(o, "getIdentifier"):
        try:
            return {"type": cls, "identifier": o.getIdentifier()}
        except BaseException:
            pass
    return str(o)


def make_value(type_id, v):
    """Build an SDValue for a property type id ('float', 'float2', 'ColorRGBA', enum...)."""
    from sd.api import sdbasetypes
    if isinstance(v, dict) and "enum" in v:
        from sd.api.sdvalueenum import SDValueEnum
        return SDValueEnum.sFromValueId(type_id, v["enum"])
    name = type_id[0].upper() + type_id[1:]
    try:
        mod = importlib.import_module("sd.api.sdvalue" + type_id.lower())
        cls = getattr(mod, "SDValue" + name)
    except BaseException:
        # probably an enum type
        from sd.api.sdvalueenum import SDValueEnum
        if isinstance(v, str):
            return SDValueEnum.sFromValueId(type_id, v)
        return SDValueEnum.sFromValue(type_id, int(v))
    base = getattr(sdbasetypes, type_id, None)
    if base is not None and isinstance(v, (list, tuple)):
        return cls.sNew(base(*v))
    if type_id in ("int",):
        v = int(v)
    elif type_id in ("float", "double"):
        v = float(v)
    elif type_id == "bool":
        v = bool(v)
    return cls.sNew(v)


def graph(graph_id=None):
    """Current graph, or a graph found by identifier in loaded user packages."""
    global _LAST_GRAPH
    if not graph_id:
        g = _ui().getCurrentGraph()
        if g is None:
            g = _LAST_GRAPH
        if g is None:
            raise RuntimeError("No graph is open in Designer")
        return g
    for pkg in _pm().getUserPackages():
        for r in _iter_resources(pkg):
            if r.getIdentifier() == graph_id and hasattr(r, "getNodes"):
                return r
    raise RuntimeError("Graph %r not found in user packages" % graph_id)


_LAST_GRAPH = None


def _open_in_editor(res):
    global _LAST_GRAPH
    if hasattr(res, "getNodes"):
        _LAST_GRAPH = res
    try:
        _app().getUIMgr().openResourceInEditor(res)
    except BaseException as e:
        print("openResourceInEditor failed: %s" % e)


def _iter_resources(pkg):
    stack = list(pkg.getChildrenResources(False))
    while stack:
        r = stack.pop()
        yield r
        try:
            stack.extend(r.getChildren(False))
        except BaseException:
            pass


def node(node_id, graph_id=None):
    n = graph(graph_id).getNodeFromId(str(node_id))
    if n is None:
        raise RuntimeError("Node %r not found" % node_id)
    return n


# ------------------------------------------------------------------ queries
def status():
    app = _app()
    g = _ui().getCurrentGraph()
    pkgs = []
    for p in _pm().getUserPackages():
        pkgs.append({
            "file": p.getFilePath(),
            "modified": p.isModified(),
            "graphs": [r.getIdentifier() for r in _iter_resources(p) if hasattr(r, "getNodes")],
        })
    return {
        "designer_version": app.getVersion(),
        "current_graph": g.getIdentifier() if g else None,
        "user_packages": pkgs,
    }


def _prop_info(n, p, with_value=True):
    d = {"id": p.getId(), "type": p.getType().getId(), "label": p.getLabel()}
    if with_value:
        try:
            d["value"] = to_py(n.getPropertyValue(p))
        except BaseException as e:
            d["value"] = "<%s>" % e
    return d


def graph_info(graph_id=None):
    g = graph(graph_id)
    nodes = []
    conns = []
    for n in g.getNodes():
        nid = n.getIdentifier()
        d = n.getDefinition()
        info = {
            "id": nid,
            "definition": d.getId(),
            "label": d.getLabel(),
            "pos": to_py(n.getPosition()),
            "outputs": [p.getId() for p in n.getProperties(SDPropertyCategory.Output)],
        }
        res = n.getReferencedResource()
        if res is not None:
            info["instance_of"] = res.getUrl()
        nodes.append(info)
        for p in n.getProperties(SDPropertyCategory.Input):
            if not p.isConnectable():
                continue
            for c in n.getPropertyConnections(p):
                conns.append({
                    "from": c.getInputPropertyNode().getIdentifier(),
                    "from_output": c.getInputProperty().getId(),
                    "to": nid,
                    "to_input": p.getId(),
                })
    return {"graph": g.getIdentifier(), "nodes": nodes, "connections": conns}


def node_info(node_id, graph_id=None):
    n = node(node_id, graph_id)
    ins, params = [], []
    for p in n.getProperties(SDPropertyCategory.Input):
        if type(p.getType()).__name__ == "SDTypeTexture":
            ins.append(_prop_info(n, p, False))
        else:
            params.append(_prop_info(n, p))
    return {
        "id": n.getIdentifier(),
        "definition": n.getDefinition().getId(),
        "pos": to_py(n.getPosition()),
        "inputs": ins,
        "params": params,
        "outputs": [_prop_info(n, p, False) for p in n.getProperties(SDPropertyCategory.Output)],
    }


def list_library(filter=""):
    """List .sbs packages of the default Designer library (resources/packages)."""
    root = os.path.join(_app().getPath(SDApplicationPath.DefaultResourcesDir), "packages")
    files = sorted(glob.glob(os.path.join(root, "*.sbs")))
    names = [os.path.splitext(os.path.basename(f))[0] for f in files]
    f = (filter or "").lower()
    return [n for n in names if f in n.lower()]


def _library_resource(name, graph_name=None):
    root = os.path.join(_app().getPath(SDApplicationPath.DefaultResourcesDir), "packages")
    path = name if os.path.isabs(name) else os.path.join(root, name if name.endswith(".sbs") else name + ".sbs")
    if not os.path.exists(path):
        base = os.path.splitext(os.path.basename(name))[0].lower()
        similar = [n for n in list_library() if any(w in n.lower() for w in base.split("_") if len(w) > 2)][:30]
        raise RuntimeError("library package %r not found. Similar: %s" % (name, similar))
    pkg = _pm().getUserPackageFromFilePath(path) or _pm().loadUserPackage(path, True)
    if pkg is None:
        raise RuntimeError("could not load %s" % path)
    graphs = [r for r in _iter_resources(pkg) if hasattr(r, "getNodes")]
    # only compositing graphs can be instanced (packages also hold function graphs, often listed first);
    # prefer the one named like the package
    comp = [r for r in graphs if type(r).__name__ == "SDSBSCompGraph"]
    base = os.path.splitext(os.path.basename(path))[0].lower()
    comp.sort(key=lambda r: (r.getIdentifier().lower() != base, r.getIdentifier().lower() not in base))
    graphs = comp + [r for r in graphs if r not in comp]
    if graph_name:
        r = pkg.findResourceFromUrl(graph_name)
        if r is None:
            raise RuntimeError("graph %r not in %s; has %s" % (graph_name, path, [g.getIdentifier() for g in graphs]))
        return r
    if not graphs:
        raise RuntimeError("no graphs in %s" % path)
    return graphs[0]


# ------------------------------------------------------------------ edits
def _apply_params(n, params):
    errors = {}
    for k, v in (params or {}).items():
        try:
            p = n.getPropertyFromId(k, SDPropertyCategory.Input)
            if p is None:
                raise RuntimeError("no input property %r" % k)
            n.setInputPropertyValueFromId(k, make_value(p.getType().getId(), v))
        except BaseException as e:
            errors[k] = str(e)
    return errors


def create_node(definition=None, library=None, library_graph=None, x=0, y=0,
                params=None, graph_id=None):
    g = graph(graph_id)
    if library:
        open_before = {p.getFilePath() for p in _pm().getUserPackages()}
        res = _library_resource(library, library_graph)
        n = g.newInstanceNode(res)
        # we opened the library package only to reach its graph: close it again so it doesn't
        # pile up in the Explorer (the instance keeps working, Designer holds it as a dependency)
        lib_pkg = res.getPackage()
        if lib_pkg is not None and lib_pkg.getFilePath() not in open_before:
            try:
                _pm().unloadUserPackage(lib_pkg)
            except BaseException:
                pass
    else:
        if "::" not in definition:
            definition = "sbs::compositing::" + definition
        n = g.newNode(definition)
    n.setPosition(float2(float(x), float(y)))
    errs = _apply_params(n, params)
    out = node_info(n.getIdentifier(), graph_id)
    if errs:
        out["param_errors"] = errs
    return out


def set_params(node_id, params, graph_id=None):
    n = node(node_id, graph_id)
    errs = _apply_params(n, params)
    return {"ok": not errs, "errors": errs}


def connect(from_node, to_node, to_input="input1", from_output=None, graph_id=None):
    a = node(from_node, graph_id)
    b = node(to_node, graph_id)
    if not from_output:
        from_output = a.getProperties(SDPropertyCategory.Output)[0].getId()
    a.newPropertyConnectionFromId(from_output, b, to_input)
    return {"from": from_node, "from_output": from_output, "to": to_node, "to_input": to_input}


def disconnect(node_id, input_id, graph_id=None):
    n = node(node_id, graph_id)
    n.deletePropertyConnections(n.getPropertyFromId(input_id, SDPropertyCategory.Input))
    return True


def delete_nodes(node_ids, graph_id=None):
    g = graph(graph_id)
    for nid in node_ids:
        g.deleteNode(node(nid, graph_id))
    return len(node_ids)


def move_node(node_id, x, y, graph_id=None):
    node(node_id, graph_id).setPosition(float2(float(x), float(y)))
    return True


def new_graph(name="new_graph", package_path=None, open_in_editor=True):
    from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
    pm = _pm()
    pkg = None
    if package_path:
        pkg = pm.getUserPackageFromFilePath(package_path)
        if pkg is None and os.path.exists(package_path):
            pkg = pm.loadUserPackage(package_path, True)
    if pkg is None:
        pkg = pm.newUserPackage()
    g = SDSBSCompGraph.sNew(pkg)
    g.setIdentifier(name)
    global _LAST_GRAPH
    _LAST_GRAPH = g
    if package_path:
        pm.savePackageAs(pkg, package_path)
    if open_in_editor:
        _open_in_editor(g)
    return {"graph": g.getIdentifier(), "package": pkg.getFilePath()}


def open_package(path, graph_id=None):
    pm = _pm()
    pkg = pm.getUserPackageFromFilePath(path) or pm.loadUserPackage(path, True)
    graphs = [r for r in _iter_resources(pkg) if hasattr(r, "getNodes")]
    target = None
    if graph_id:
        target = next((r for r in graphs if r.getIdentifier() == graph_id), None)
    elif graphs:
        target = graphs[0]
    if target is not None:
        _open_in_editor(target)
    return {"package": pkg.getFilePath(), "graphs": [r.getIdentifier() for r in graphs],
            "opened": target.getIdentifier() if target else None}


def save_package(path=None, graph_id=None):
    g = graph(graph_id)
    pkg = g.getPackage()
    if path:
        _pm().savePackageAs(pkg, path)
    else:
        if not pkg.getFilePath():
            raise RuntimeError("Package has never been saved; pass a path")
        _pm().savePackage(pkg)
    return pkg.getFilePath()


def render_node(node_id, output=None, path=None, max_size=1024, graph_id=None):
    """Compute the graph and save a node output to an image file. Returns path."""
    g = graph(graph_id)
    n = node(node_id, graph_id)
    outs = n.getProperties(SDPropertyCategory.Output)
    p = n.getPropertyFromId(output, SDPropertyCategory.Output) if output else outs[0]
    v = None
    if True:
        # Designer only computes nodes that feed an Output node: add a temporary one.
        tmp = g.newNode("sbs::compositing::output")
        try:
            n.newPropertyConnectionFromId(p.getId(), tmp, "inputNodeOutput")
            g.compute()
            # only graph *outputs* are guaranteed fresh -> read from the temp output node
            v = tmp.getPropertyValue(tmp.getProperties(SDPropertyCategory.Output)[0])
            if v is not None:
                tex = v.get()
                if path is None:
                    path = os.path.join(tempfile.gettempdir(), "claude_sd_%s_%s.png" % (node_id, p.getId()))
                tex.save(path)
        finally:
            g.deleteNode(tmp)
        if v is None:
            raise RuntimeError("Output has no value (not a texture output?)")
        return _finish_render(path, tex, max_size)
    tex = v.get()
    if path is None:
        path = os.path.join(tempfile.gettempdir(), "claude_sd_%s_%s.png" % (node_id, p.getId()))
    tex.save(path)
    return _finish_render(path, tex, max_size)


def _finish_render(path, tex, max_size):
    if max_size and path.lower().endswith(".png"):
        try:
            from PySide6.QtGui import QImage
            from PySide6.QtCore import Qt
            img = QImage(path)
            if not img.isNull() and max(img.width(), img.height()) > max_size:
                img.scaled(max_size, max_size, Qt.KeepAspectRatio,
                           Qt.SmoothTransformation).save(path)
        except BaseException:
            pass
    return {"path": path, "size": to_py(tex.getSize())}


def node_definitions(filter="", graph_id=None):
    f = (filter or "").lower()
    defs = graph(graph_id).getNodeDefinitions()
    return [d.getId() for d in defs if f in d.getId().lower()]


# ------------------------------------------------------------------ view
def focus_nodes(node_ids, graph_id=None, select=True, max_zoom=1.5):
    """Show nodes in the graph view: open the graph if needed, fit them in view, select them.

    -> {"found": n, "pending": True} when the graph had to be opened first (call again once its view exists).
    """
    from PySide6 import QtCore, QtWidgets
    u = _app().getUIMgr()
    g = graph(graph_id)
    nodes = [n for n in (g.getNodeFromId(str(i)) for i in node_ids) if n is not None]
    if not nodes:
        return {"found": 0}
    cur = _ui().getCurrentGraph()
    if cur is None or cur.getIdentifier() != g.getIdentifier():
        _open_in_editor(g)
        return {"found": len(nodes), "pending": True}
    vid = None
    for i in range(u.getGraphViewIDCount()):
        v = u.getGraphViewIDAt(i)
        vg = u.getGraphFromGraphViewID(v)
        if vg is not None and vg.getIdentifier() == g.getIdentifier():
            vid = v
            break
    if vid is None:
        return {"found": len(nodes), "pending": True}
    w = _ui().getGraphView(vid)
    gv = w if isinstance(w, QtWidgets.QGraphicsView) else (w.findChild(QtWidgets.QGraphicsView) if w else None)
    if gv is None or gv.scene() is None:
        u.focusGraphNode(vid, nodes[0])
        return {"found": len(nodes)}
    rect, boxes = QtCore.QRectF(), []
    for n in nodes:
        b = u.getGraphNodeBBox(vid, n)          # scene coords: x, y, z = width, w = height
        r = QtCore.QRectF(b.x, b.y, b.z, b.w)
        boxes.append(r)
        rect = rect.united(r) if not rect.isNull() else r
    rect.adjust(-80, -80, 80, 80)
    gv.fitInView(rect, QtCore.Qt.KeepAspectRatio)
    s = gv.transform().m11()
    if s > max_zoom:                             # a single node shouldn't fill the whole view
        gv.scale(max_zoom / s, max_zoom / s)
    gv.centerOn(rect.center())
    if select:
        sc = gv.scene()
        sc.clearSelection()
        for r in boxes:
            for it in sc.items(r.center()):      # topmost selectable node-sized item = the node
                if it.flags() & QtWidgets.QGraphicsItem.ItemIsSelectable and \
                        it.sceneBoundingRect().width() < r.width() + 60 and it.sceneBoundingRect().height() < r.height() + 80:
                    it.setSelected(True)
                    break
    return {"found": len(nodes)}
