import networkx as nx

def _parse_hint_tags(txt: str) -> tuple[str | None, str, str]:
    """Parse layout hint, matrix style, and tree direction from text."""
    matrix_style = "axis" if "#style:axis" in txt else "cross"
    tree_dir = "lr" if "#dir:lr" in txt else "td"
    if "#layout:matrix" in txt:
        return "matrix", matrix_style, tree_dir
    if "#layout:cycle" in txt:
        return "cycle", matrix_style, tree_dir
    if any(
        k in txt
        for k in ("#layout:wheel", "#layout:star-cycle", "#layout:star_cycle")
    ):
        return "wheel", matrix_style, tree_dir
    if "#layout:radial" in txt:
        return "radial", matrix_style, tree_dir
    if "#layout:concentric" in txt:
        return "concentric", matrix_style, tree_dir
    if any(k in txt for k in ("#layout:value_chain", "#layout:value-chain")):
        return "value_chain", matrix_style, tree_dir
    if "#layout:tree" in txt:
        return "tree", matrix_style, tree_dir
    if "#layout:sugiyama" in txt:
        return "sugiyama", matrix_style, tree_dir
    return None, matrix_style, tree_dir


def _extract_layout_hints(
    elements: list[dict],
) -> tuple[str | None, str, str, str | None]:
    """Extract metadata tags provided by LLM from text elements."""
    for el in elements:
        if el.get("type") == "text":
            hint, matrix_style, tree_dir = _parse_hint_tags(el.get("text", ""))
            if hint:
                return hint, matrix_style, tree_dir, el.get("id")
    return None, "cross", "td", None


def _cleanup_metadata_node(elements: list[dict], metadata_node_id: str | None) -> None:
    """Remove metadata text node and its bindings so it doesn't clutter the diagram."""
    if not metadata_node_id:
        return
    elements[:] = [el for el in elements if el.get("id") != metadata_node_id]
    for el in elements:
        if el.get("boundElements") is not None:
            el["boundElements"] = [
                b
                for b in el["boundElements"]
                if isinstance(b, dict) and b.get("id") != metadata_node_id
            ]


def _build_topology_graph(elements: list[dict]) -> nx.Graph:
    """Construct an undirected graph of connected shapes and arrows."""
    G = nx.Graph()
    for el in elements:
        if el.get("type") in ("rectangle", "ellipse", "diamond"):
            G.add_node(el["id"])
        elif el.get("type") == "arrow":
            sb = el.get("startBinding", {})
            eb = el.get("endBinding", {})
            sid = (
                sb.get("elementId")
                if isinstance(sb, dict)
                else (sb if isinstance(sb, str) else None)
            )
            eid = (
                eb.get("elementId")
                if isinstance(eb, dict)
                else (eb if isinstance(eb, str) else None)
            )
            if sid in G and eid in G:
                G.add_edge(sid, eid)
    return G


def _detect_wheel_graph(G_eval: nx.Graph, degrees: dict, max_deg: int) -> bool:
    """Detect if topology matches a wheel graph (hub + outer cycle)."""
    if len(G_eval.nodes) < 4 or max_deg < 3:
        return False
    hub = max(
        degrees,
        key=lambda n: (
            degrees[n],
            1 if any(k in n.lower() for k in ("hub", "core", "center")) else 0,
        ),
    )
    outer_nodes = [n for n in G_eval.nodes if n != hub]
    if len(outer_nodes) >= 3:
        try:
            g_outer = G_eval.subgraph(outer_nodes)
            outer_cycles = nx.cycle_basis(g_outer)
            if outer_cycles:
                longest = max(outer_cycles, key=len)
                if len(longest) >= max(3, int(len(outer_nodes) * 0.7)):
                    hub_neighbors = set(G_eval.neighbors(hub))
                    if len(hub_neighbors.intersection(longest)) >= int(
                        len(longest) * 0.7
                    ):
                        return True
        except Exception:
            pass
    return False


def _detect_topology(elements: list[dict]) -> tuple[bool, bool, bool, bool, bool]:
    """Detect graph topology patterns (wheel, radial, cycle, tree, chain)."""
    G = _build_topology_graph(elements)
    if not G.nodes:
        return False, False, False, False, False

    active_nodes = [n for n in G.nodes if G.degree(n) > 0]
    G_eval = G.subgraph(active_nodes) if len(active_nodes) >= 3 else G
    degrees = dict(G_eval.degree())
    max_deg = max(degrees.values()) if degrees else 0

    is_wheel = _detect_wheel_graph(G_eval, degrees, max_deg)
    is_radial = (
        not is_wheel and max_deg >= len(G_eval.nodes) - 2 and len(G_eval.nodes) > 3
    )
    is_cycle = False
    if not is_wheel:
        try:
            basis = nx.cycle_basis(G_eval)
            if basis and len(max(basis, key=len)) == len(G_eval.nodes):
                is_cycle = True
        except Exception:
            pass

    is_tree = False
    if not is_wheel and not is_cycle and len(G_eval.nodes) > 3:
        try:
            if nx.is_tree(G_eval):
                is_tree = True
        except Exception:
            pass

    is_chain = False
    if not is_wheel and not is_cycle and not is_tree and len(G_eval.nodes) > 2:
        deg_vals = list(degrees.values())
        d2 = sum(1 for d in deg_vals if d == 2)
        d1 = sum(1 for d in deg_vals if d == 1)
        if d2 >= len(G_eval.nodes) - 2 and d1 <= 2:
            is_chain = True

    return is_wheel, is_radial, is_cycle, is_tree, is_chain


def _dispatch_hinted_layout(
    elements: list[dict], layout_hint: str, matrix_style: str, tree_dir: str
) -> None:
    """Apply layout according to explicit hint tag."""
    if layout_hint == "matrix":
        from core.layouts.matrix_layout import apply_matrix_layout

        apply_matrix_layout(elements, style=matrix_style)
    elif layout_hint == "wheel":
        from core.layouts.wheel_layout import apply_wheel_layout

        apply_wheel_layout(elements)
    elif layout_hint == "cycle":
        from core.layouts.cycle_layout import apply_cycle_layout

        apply_cycle_layout(elements)
    elif layout_hint == "radial":
        from core.layouts.radial_layout import apply_radial_layout

        apply_radial_layout(elements)
    elif layout_hint == "concentric":
        from core.layouts.concentric_layout import apply_concentric_layout

        apply_concentric_layout(elements)
    elif layout_hint == "value_chain":
        from core.layouts.value_chain_layout import apply_value_chain_layout

        apply_value_chain_layout(elements)
    elif layout_hint == "tree":
        from core.layouts.tree_layout import apply_tree_layout

        apply_tree_layout(elements, direction=tree_dir)
    else:
        from core.layouts.sugiyama_layout import apply_sugiyama_layout

        apply_sugiyama_layout(elements)


def _dispatch_auto_layout(
    elements: list[dict], topology: tuple[bool, bool, bool, bool, bool], tree_dir: str
) -> None:
    """Apply fallback layout according to detected topology."""
    is_wheel, is_radial, is_cycle, is_tree, is_chain = topology
    if is_wheel:
        from core.layouts.wheel_layout import apply_wheel_layout

        apply_wheel_layout(elements)
    elif is_cycle:
        from core.layouts.cycle_layout import apply_cycle_layout

        apply_cycle_layout(elements)
    elif is_radial:
        from core.layouts.radial_layout import apply_radial_layout

        apply_radial_layout(elements)
    elif is_tree:
        from core.layouts.tree_layout import apply_tree_layout

        apply_tree_layout(elements, direction=tree_dir)
    elif is_chain:
        from core.layouts.value_chain_layout import apply_value_chain_layout

        apply_value_chain_layout(elements)
    elif _has_enclosing_containers(elements):
        return
    else:
        from core.layouts.sugiyama_layout import apply_sugiyama_layout

        apply_sugiyama_layout(elements)


def apply_smart_layout(elements: list[dict]) -> None:
    """Analyze diagram topology and metadata to apply the correct layout engine."""
    layout_hint, matrix_style, tree_dir, metadata_node_id = _extract_layout_hints(
        elements
    )
    _cleanup_metadata_node(elements, metadata_node_id)
    if layout_hint:
        _dispatch_hinted_layout(elements, layout_hint, matrix_style, tree_dir)
    else:
        topology = _detect_topology(elements)
        _dispatch_auto_layout(elements, topology, tree_dir)


def _has_enclosing_containers(elements: list[dict]) -> bool:
    """Detect if the diagram contains one or more enclosing container boxes."""
    shapes = [el for el in elements if el.get("type") in ("rectangle", "ellipse", "diamond")]
    for shape in shapes:
        sx, sy = shape.get("x", 0), shape.get("y", 0)
        sw, sh = shape.get("width", 100), shape.get("height", 100)
        for o in shapes:
            if o is not shape:
                ox, oy = o.get("x", 0), o.get("y", 0)
                ow, oh = o.get("width", 50), o.get("height", 50)
                if sx <= ox and sy <= oy and (sx + sw) >= (ox + ow) and (sy + sh) >= (oy + oh) and (sw * sh > ow * oh * 1.5):
                    return True
    return False


