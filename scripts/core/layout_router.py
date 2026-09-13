import networkx as nx

def apply_smart_layout(elements: list[dict]) -> None:
    """Analyze diagram topology and metadata to apply the correct layout engine."""
    layout_hint = None
    matrix_style = "cross"
    tree_dir = "td"
    metadata_node_id = None
    
    # Extract metadata tags provided by LLM
    for el in elements:
        if el.get("type") == "text":
            txt = el.get("text", "")
            if "#layout:matrix" in txt:
                layout_hint = "matrix"
                if "#style:axis" in txt:
                    matrix_style = "axis"
                metadata_node_id = el.get("id")
                break
            elif "#layout:cycle" in txt:
                layout_hint = "cycle"
                metadata_node_id = el.get("id")
                break
            elif "#layout:wheel" in txt or "#layout:star-cycle" in txt or "#layout:star_cycle" in txt:
                layout_hint = "wheel"
                metadata_node_id = el.get("id")
                break
            elif "#layout:radial" in txt:
                layout_hint = "radial"
                metadata_node_id = el.get("id")
                break
            elif "#layout:concentric" in txt:
                layout_hint = "concentric"
                metadata_node_id = el.get("id")
                break
            elif "#layout:value_chain" in txt or "#layout:value-chain" in txt:
                layout_hint = "value_chain"
                metadata_node_id = el.get("id")
                break
            elif "#layout:tree" in txt:
                layout_hint = "tree"
                if "#dir:lr" in txt:
                    tree_dir = "lr"
                metadata_node_id = el.get("id")
                break
            elif "#layout:sugiyama" in txt:
                layout_hint = "sugiyama"
                metadata_node_id = el.get("id")
                break

    # Remove the metadata text node from the final output so it doesn't clutter the diagram
    if metadata_node_id:
        elements[:] = [el for el in elements if el.get("id") != metadata_node_id]
        for el in elements:
            if el.get("boundElements") is not None:
                el["boundElements"] = [b for b in el["boundElements"] if isinstance(b, dict) and b.get("id") != metadata_node_id]

    # Build Graph for Topology Analysis (only if we need auto-detection fallback)
    is_wheel = False
    is_radial = False
    is_cycle = False
    is_tree = False
    is_chain = False
    
    if not layout_hint:
        G = nx.Graph()
        for el in elements:
            if el.get("type") in ("rectangle", "ellipse", "diamond"):
                G.add_node(el["id"])
            elif el.get("type") == "arrow":
                sb = el.get("startBinding", {})
                eb = el.get("endBinding", {})
                sid = sb.get("elementId") if isinstance(sb, dict) else (sb if isinstance(sb, str) else None)
                eid = eb.get("elementId") if isinstance(eb, dict) else (eb if isinstance(eb, str) else None)
                if sid and eid:
                    G.add_edge(sid, eid)
                    
        if G.nodes:
            degrees = dict(G.degree())
            max_deg = max(degrees.values()) if degrees else 0

            # 0. Wheel graph (Hub + Outer Cycle) detection
            if len(G.nodes) >= 4 and max_deg >= 3:
                hub_candidate = max(degrees, key=lambda n: (degrees[n], 1 if "hub" in n.lower() else 0))
                outer_nodes = [n for n in G.nodes if n != hub_candidate]
                if len(outer_nodes) >= 3:
                    try:
                        g_outer = G.subgraph(outer_nodes)
                        outer_cycles = nx.cycle_basis(g_outer)
                        if outer_cycles:
                            longest_cycle = max(outer_cycles, key=len)
                            # Outer cycle must span at least 70% of outer nodes
                            if len(longest_cycle) >= max(3, int(len(outer_nodes) * 0.7)):
                                hub_neighbors = set(G.neighbors(hub_candidate))
                                cycle_conn = len(hub_neighbors.intersection(longest_cycle))
                                if cycle_conn >= int(len(longest_cycle) * 0.7):
                                    is_wheel = True
                    except Exception:
                        pass
            
            # 1. Star graph (Hub and Spoke) detection
            if not is_wheel and max_deg >= len(G.nodes) - 2 and len(G.nodes) > 3:
                is_radial = True
            
            # 2. Cycle detection
            if not is_wheel:
                try:
                    basis = nx.cycle_basis(G)
                    if basis and len(max(basis, key=len)) == len(G.nodes):
                        is_cycle = True
                except Exception:
                    pass
                
            # 3. Spanning Tree structure detection
            if not is_wheel and not is_cycle and len(G.nodes) > 3:
                try:
                    if nx.is_tree(G):
                        is_tree = True
                except Exception:
                    pass
                    
            # 4. Chain detection (highly linear layout)
            if not is_wheel and not is_cycle and not is_tree and len(G.nodes) > 2:
                deg_vals = list(degrees.values())
                deg_2_count = sum(1 for d in deg_vals if d == 2)
                deg_1_count = sum(1 for d in deg_vals if d == 1)
                if deg_2_count >= len(G.nodes) - 2 and deg_1_count <= 2:
                    is_chain = True

    # --- Routing Execution ---
    if layout_hint:
        # Prioritize explicit hints from the user/LLM
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
        else: # sugiyama
            from core.layouts.sugiyama_layout import apply_sugiyama_layout
            apply_sugiyama_layout(elements)
    else:
        # Fallback to automatic topology detection
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
        else:
            from core.layouts.sugiyama_layout import apply_sugiyama_layout
            apply_sugiyama_layout(elements)

