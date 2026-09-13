"""Tests for layout engine modules.

Each layout engine receives a list[dict] of Excalidraw elements and
applies deterministic coordinate transformations in-place. These tests
verify:
  - Empty input returns False
  - Valid input returns True and produces correct coordinates
  - Academic aesthetics (roughness=0, grayscale colors) are applied
  - Arrow re-routing produces valid geometry
"""

from __future__ import annotations

import copy
import math
from unittest.mock import patch

import pytest


# ── Test Fixtures ──────────────────────────────────────────────────

def _make_shape(sid: str, x: float = 0, y: float = 0,
                w: float = 150, h: float = 100,
                shape_type: str = "rectangle") -> dict:
    """Create a minimal Excalidraw shape element."""
    return {
        "id": sid, "type": shape_type,
        "x": x, "y": y, "width": w, "height": h,
        "boundElements": [],
    }


def _make_arrow(aid: str, start_id: str, end_id: str) -> dict:
    """Create a minimal Excalidraw arrow element."""
    return {
        "id": aid, "type": "arrow",
        "x": 0, "y": 0,
        "points": [[0, 0], [100, 0]],
        "startBinding": {"elementId": start_id},
        "endBinding": {"elementId": end_id},
        "boundElements": [],
    }


def _hub_spoke_elements(n_spokes: int = 4) -> list[dict]:
    """Create a hub-and-spoke graph (1 center + n_spokes leaves)."""
    hub = _make_shape("hub", 400, 300)
    elements = [hub]
    for i in range(n_spokes):
        spoke = _make_shape(f"s{i}", 100 * i, 100 * i)
        arrow = _make_arrow(f"a{i}", "hub", f"s{i}")
        elements.extend([spoke, arrow])
    return elements


def _cycle_elements(n: int = 4) -> list[dict]:
    """Create a simple cycle graph: 0→1→2→...→n-1→0."""
    elements: list[dict] = []
    for i in range(n):
        elements.append(_make_shape(f"c{i}", 100 * i, 0))
    for i in range(n):
        elements.append(_make_arrow(f"ca{i}", f"c{i}", f"c{(i + 1) % n}"))
    return elements


def _tree_elements() -> list[dict]:
    """Create a simple tree: root → child1, root → child2."""
    return [
        _make_shape("root", 300, 0),
        _make_shape("child1", 100, 200),
        _make_shape("child2", 500, 200),
        _make_arrow("a1", "root", "child1"),
        _make_arrow("a2", "root", "child2"),
    ]


def _chain_elements(n: int = 4) -> list[dict]:
    """Create a linear chain: 0→1→2→...→n-1."""
    elements: list[dict] = []
    for i in range(n):
        elements.append(_make_shape(f"v{i}", 200 * i, 0))
    for i in range(n - 1):
        elements.append(_make_arrow(f"va{i}", f"v{i}", f"v{i + 1}"))
    return elements


def _wheel_elements(n_outer: int = 5) -> list[dict]:
    """Create a wheel graph: 1 central hub + n_outer outer nodes connected in a cycle and to the hub."""
    hub = _make_shape("hub", 0, 0)
    elements = [hub]
    for i in range(n_outer):
        elements.append(_make_shape(f"w{i}", 100 * i, 100 * i))
    for i in range(n_outer):
        elements.append(_make_arrow(f"ca{i}", f"w{i}", f"w{(i + 1) % n_outer}"))
    for i in range(n_outer):
        elements.append(_make_arrow(f"sa{i}", "hub", f"w{i}"))
    return elements



# ── Shared Assertions ──────────────────────────────────────────────

def _assert_academic_aesthetics(elements: list[dict]) -> None:
    """Verify Academic Grayscale Theme applied to all shapes."""
    for el in elements:
        if el.get("type") in ("rectangle", "ellipse", "diamond"):
            assert el["roughness"] == 0, f"Shape {el['id']} should have roughness=0"


def _assert_no_nan_coords(elements: list[dict]) -> None:
    """Verify no NaN or Inf in coordinates."""
    for el in elements:
        x = el.get("x", 0)
        y = el.get("y", 0)
        assert not (math.isnan(x) or math.isinf(x)), f"Bad x in {el['id']}: {x}"
        assert not (math.isnan(y) or math.isinf(y)), f"Bad y in {el['id']}: {y}"
        for pt in el.get("points", []):
            for v in pt:
                assert not (math.isnan(v) or math.isinf(v)), f"Bad point in {el['id']}"


# ── Radial Layout Tests ───────────────────────────────────────────

class TestRadialLayout:
    def test_empty_returns_false(self):
        from core.layouts.radial_layout import apply_radial_layout
        assert apply_radial_layout([]) is False

    def test_hub_spoke_returns_true(self):
        from core.layouts.radial_layout import apply_radial_layout
        elements = _hub_spoke_elements(5)
        assert apply_radial_layout(elements) is True

    def test_hub_centered(self):
        from core.layouts.radial_layout import apply_radial_layout
        elements = _hub_spoke_elements(4)
        apply_radial_layout(elements)
        hub = next(e for e in elements if e["id"] == "hub")
        # Hub should be approximately centered at (600, 400) minus half its dimensions
        assert abs(hub["x"] - (600 - 75)) < 1
        assert abs(hub["y"] - (400 - 50)) < 1

    def test_spokes_equidistant(self):
        from core.layouts.radial_layout import apply_radial_layout
        elements = _hub_spoke_elements(4)
        apply_radial_layout(elements)
        spokes = [e for e in elements if e["id"].startswith("s")]
        # All spokes should be at the same distance from center
        distances = []
        for s in spokes:
            cx = s["x"] + s["width"] / 2
            cy = s["y"] + s["height"] / 2
            distances.append(math.hypot(cx - 600, cy - 400))
        assert max(distances) - min(distances) < 1.0

    def test_aesthetics_applied(self):
        from core.layouts.radial_layout import apply_radial_layout
        elements = _hub_spoke_elements(3)
        apply_radial_layout(elements)
        _assert_academic_aesthetics(elements)
        _assert_no_nan_coords(elements)


# ── Cycle Layout Tests ────────────────────────────────────────────

class TestCycleLayout:
    def test_empty_returns_false(self):
        from core.layouts.cycle_layout import apply_cycle_layout
        assert apply_cycle_layout([]) is False

    def test_cycle_returns_true(self):
        from core.layouts.cycle_layout import apply_cycle_layout
        elements = _cycle_elements(4)
        assert apply_cycle_layout(elements) is True

    def test_nodes_on_circle(self):
        from core.layouts.cycle_layout import apply_cycle_layout
        elements = _cycle_elements(4)
        apply_cycle_layout(elements)
        shapes = [e for e in elements if e["type"] in ("rectangle", "ellipse")]
        # All nodes should be at same distance from center (600, 400)
        distances = []
        for s in shapes:
            cx = s["x"] + s["width"] / 2
            cy = s["y"] + s["height"] / 2
            distances.append(math.hypot(cx - 600, cy - 400))
        assert max(distances) - min(distances) < 1.0

    def test_aesthetics_applied(self):
        from core.layouts.cycle_layout import apply_cycle_layout
        elements = _cycle_elements(3)
        apply_cycle_layout(elements)
        _assert_academic_aesthetics(elements)


# ── Matrix Layout Tests ───────────────────────────────────────────

class TestMatrixLayout:
    def test_empty_returns_false(self):
        from core.layouts.matrix_layout import apply_matrix_layout
        assert apply_matrix_layout([]) is False

    def test_cross_style_adds_lines(self):
        from core.layouts.matrix_layout import apply_matrix_layout
        elements = [_make_shape("q1", 0, 0), _make_shape("q2", 300, 0),
                     _make_shape("q3", 0, 300), _make_shape("q4", 300, 300)]
        original_count = len(elements)
        result = apply_matrix_layout(elements, style="cross")
        assert result is True
        # Cross style adds 2 background lines (vertical + horizontal)
        assert len(elements) == original_count + 2

    def test_axis_style_adds_axes(self):
        from core.layouts.matrix_layout import apply_matrix_layout
        elements = [_make_shape("q1", 0, 0), _make_shape("q2", 300, 300)]
        original_count = len(elements)
        result = apply_matrix_layout(elements, style="axis")
        assert result is True
        assert len(elements) == original_count + 2

    def test_aesthetics_applied(self):
        from core.layouts.matrix_layout import apply_matrix_layout
        elements = [_make_shape("q1", 0, 0), _make_shape("q2", 300, 300)]
        apply_matrix_layout(elements)
        _assert_academic_aesthetics(elements)


# ── Sugiyama Layout Tests ─────────────────────────────────────────

class TestSugiyamaLayout:
    def test_empty_returns_false(self):
        from core.layouts.sugiyama_layout import apply_sugiyama_layout
        assert apply_sugiyama_layout([]) is False

    def test_dag_returns_true(self):
        from core.layouts.sugiyama_layout import apply_sugiyama_layout
        elements = _tree_elements()
        assert apply_sugiyama_layout(elements) is True

    def test_parent_above_children(self):
        from core.layouts.sugiyama_layout import apply_sugiyama_layout
        elements = _tree_elements()
        apply_sugiyama_layout(elements)
        root = next(e for e in elements if e["id"] == "root")
        child1 = next(e for e in elements if e["id"] == "child1")
        # In top-down Sugiyama, root y should be less than child y
        assert root["y"] < child1["y"]

    def test_aesthetics_applied(self):
        from core.layouts.sugiyama_layout import apply_sugiyama_layout
        elements = _tree_elements()
        apply_sugiyama_layout(elements)
        _assert_academic_aesthetics(elements)
        _assert_no_nan_coords(elements)


# ── Tree Layout Tests ─────────────────────────────────────────────

class TestTreeLayout:
    def test_empty_returns_false(self):
        from core.layouts.tree_layout import apply_tree_layout
        assert apply_tree_layout([]) is False

    def test_tree_returns_true(self):
        from core.layouts.tree_layout import apply_tree_layout
        elements = _tree_elements()
        assert apply_tree_layout(elements) is True

    def test_top_down_parent_above(self):
        from core.layouts.tree_layout import apply_tree_layout
        elements = _tree_elements()
        apply_tree_layout(elements, direction="td")
        root = next(e for e in elements if e["id"] == "root")
        child1 = next(e for e in elements if e["id"] == "child1")
        assert root["y"] < child1["y"]

    def test_left_right_parent_left(self):
        from core.layouts.tree_layout import apply_tree_layout
        elements = _tree_elements()
        apply_tree_layout(elements, direction="lr")
        root = next(e for e in elements if e["id"] == "root")
        child1 = next(e for e in elements if e["id"] == "child1")
        assert root["x"] < child1["x"]

    def test_aesthetics_applied(self):
        from core.layouts.tree_layout import apply_tree_layout
        elements = _tree_elements()
        apply_tree_layout(elements)
        _assert_academic_aesthetics(elements)


# ── Value Chain Layout Tests ──────────────────────────────────────

class TestValueChainLayout:
    def test_empty_returns_false(self):
        from core.layouts.value_chain_layout import apply_value_chain_layout
        assert apply_value_chain_layout([]) is False

    def test_chain_returns_true(self):
        from core.layouts.value_chain_layout import apply_value_chain_layout
        elements = _chain_elements(4)
        assert apply_value_chain_layout(elements) is True

    def test_aesthetics_applied(self):
        from core.layouts.value_chain_layout import apply_value_chain_layout
        elements = _chain_elements(3)
        apply_value_chain_layout(elements)
        _assert_academic_aesthetics(elements)
        _assert_no_nan_coords(elements)


# ── Concentric Layout Tests ───────────────────────────────────────

class TestConcentricLayout:
    def test_empty_returns_false(self):
        from core.layouts.concentric_layout import apply_concentric_layout
        assert apply_concentric_layout([]) is False

    def test_concentric_returns_true(self):
        from core.layouts.concentric_layout import apply_concentric_layout
        elements = _hub_spoke_elements(6)
        assert apply_concentric_layout(elements) is True

    def test_aesthetics_applied(self):
        from core.layouts.concentric_layout import apply_concentric_layout
        elements = _hub_spoke_elements(4)
        apply_concentric_layout(elements)
        _assert_academic_aesthetics(elements)
        _assert_no_nan_coords(elements)


# ── Wheel Layout Tests ─────────────────────────────────────────────

class TestWheelLayout:
    def test_empty_returns_false(self):
        from core.layouts.wheel_layout import apply_wheel_layout
        assert apply_wheel_layout([]) is False

    def test_wheel_returns_true(self):
        from core.layouts.wheel_layout import apply_wheel_layout
        elements = _wheel_elements(5)
        assert apply_wheel_layout(elements) is True

    def test_hub_centered(self):
        from core.layouts.wheel_layout import apply_wheel_layout
        elements = _wheel_elements(5)
        apply_wheel_layout(elements, center_x=600, center_y=400)
        hub = next(e for e in elements if e["id"] == "hub")
        assert abs(hub["x"] - (600 - hub["width"] / 2)) < 1.0
        assert abs(hub["y"] - (400 - hub["height"] / 2)) < 1.0

    def test_outer_nodes_equidistant(self):
        from core.layouts.wheel_layout import apply_wheel_layout
        elements = _wheel_elements(5)
        apply_wheel_layout(elements, center_x=600, center_y=400, radius=260)
        outer = [e for e in elements if e["id"].startswith("w")]
        distances = []
        for o in outer:
            cx = o["x"] + o["width"] / 2
            cy = o["y"] + o["height"] / 2
            distances.append(math.hypot(cx - 600, cy - 400))
        assert max(distances) - min(distances) < 1.0
        assert abs(distances[0] - 260) < 1.0

    def test_aesthetics_applied(self):
        from core.layouts.wheel_layout import apply_wheel_layout
        elements = _wheel_elements(5)
        apply_wheel_layout(elements)
        _assert_academic_aesthetics(elements)
        _assert_no_nan_coords(elements)

    def test_spoke_and_cycle_arrows_geometry(self):
        from core.layouts.wheel_layout import apply_wheel_layout
        elements = _wheel_elements(5)
        apply_wheel_layout(elements)
        cycle_arrows = [e for e in elements if e["id"].startswith("ca")]
        spoke_arrows = [e for e in elements if e["id"].startswith("sa")]
        for ca in cycle_arrows:
            assert len(ca["points"]) == 3  # Curved with midpoint
            assert ca.get("roundness", {}).get("type") == 2
        for sa in spoke_arrows:
            assert len(sa["points"]) == 2  # Straight spoke
            assert sa.get("roundness") is None

    def test_start_node_aligned_to_top(self):
        from core.layouts.wheel_layout import apply_wheel_layout
        elements = _wheel_elements(5)
        apply_wheel_layout(elements, center_x=600, center_y=400, radius=260)
        w0 = next(e for e in elements if e["id"] == "w0")
        cx = w0["x"] + w0["width"] / 2
        cy = w0["y"] + w0["height"] / 2
        # w0 should be at 12 o'clock: x=600, y=400 - 260 = 140
        assert abs(cx - 600.0) < 1.0
        assert abs(cy - 140.0) < 1.0

    def test_bound_text_translation(self):
        from core.layouts.wheel_layout import apply_wheel_layout
        elements = _wheel_elements(5)
        text_el = {
            "id": "t_w0",
            "type": "text",
            "containerId": "w0",
            "text": "Outer Node 0",
            "x": 0.0,
            "y": 0.0,
            "width": 100.0,
            "height": 20.0,
        }
        elements.append(text_el)
        apply_wheel_layout(elements, center_x=600, center_y=400, radius=260)
        w0 = next(e for e in elements if e["id"] == "w0")
        # Text element should be translated by the same displacement as w0
        assert text_el["x"] == w0["x"]
        assert text_el["y"] == w0["y"]

    def test_dynamic_radius_clearance(self):
        from core.layouts.wheel_layout import apply_wheel_layout
        # Create wide rectangles
        elements = _wheel_elements(5)
        for el in elements:
            if el.get("type") == "rectangle":
                el["width"] = 220.0
                el["height"] = 80.0
        apply_wheel_layout(elements, center_x=600, center_y=400)
        # Verify radius expanded beyond default 260 to preserve clearance
        w0 = next(e for e in elements if e["id"] == "w0")
        cy = w0["y"] + w0["height"] / 2
        actual_radius = 400.0 - cy
        assert actual_radius >= 260.0



# ── Layout Router Tests ───────────────────────────────────────────

class TestLayoutRouter:
    def test_metadata_tag_routing(self):
        from core.layout_router import apply_smart_layout
        elements = [
            {"id": "meta", "type": "text", "text": "#layout:matrix #style:cross"},
            _make_shape("s1", 0, 0),
            _make_shape("s2", 300, 300),
        ]
        apply_smart_layout(elements)
        # Metadata text node should be removed
        assert not any(e.get("id") == "meta" for e in elements)

    def test_sugiyama_tag(self):
        from core.layout_router import apply_smart_layout
        elements = [
            {"id": "meta", "type": "text", "text": "#layout:sugiyama"},
            *_tree_elements(),
        ]
        apply_smart_layout(elements)
        # Should have applied layout without error
        root = next(e for e in elements if e.get("id") == "root")
        assert "roughness" in root  # Aesthetics applied

    def test_wheel_tag(self):
        from core.layout_router import apply_smart_layout
        elements = [
            {"id": "meta", "type": "text", "text": "#layout:wheel"},
            *_wheel_elements(5),
        ]
        apply_smart_layout(elements)
        hub = next(e for e in elements if e.get("id") == "hub")
        assert hub["strokeWidth"] == 3

    def test_wheel_autodetect(self):
        from core.layout_router import apply_smart_layout
        elements = _wheel_elements(5)
        apply_smart_layout(elements)
        hub = next(e for e in elements if e.get("id") == "hub")
        assert hub["strokeWidth"] == 3


# ── Shared Layout Seams Tests ─────────────────────────────────────

class TestSharedLayoutSeams:
    def test_sync_bound_text_translation(self):
        from services.diagram_base import sync_bound_text_translation
        shape = _make_shape("s1", 100, 100)
        shape["boundElements"] = [{"id": "t_bound", "type": "text"}]
        t_bound = {
            "id": "t_bound", "type": "text", "text": "Bound Text",
            "x": 110, "y": 110, "width": 80, "height": 20,
        }
        t_container = {
            "id": "t_cont", "type": "text", "containerId": "s1", "text": "Container Text",
            "x": 120, "y": 120, "width": 80, "height": 20,
        }
        t_other = {
            "id": "t_other", "type": "text", "text": "Unrelated",
            "x": 500, "y": 500, "width": 80, "height": 20,
        }
        elements = [shape, t_bound, t_container, t_other]

        sync_bound_text_translation(shape, elements, dx=40.0, dy=60.0)

        assert t_bound["x"] == 150.0
        assert t_bound["y"] == 170.0
        assert t_container["x"] == 160.0
        assert t_container["y"] == 180.0
        assert t_other["x"] == 500.0  # Unchanged
        assert t_other["y"] == 500.0

    def test_sync_bound_text_translation_none_id_safety(self):
        from services.diagram_base import sync_bound_text_translation
        shape = _make_shape("s1", 100, 100)
        shape["boundElements"] = [{"type": "text"}]  # Missing 'id'
        t_unrelated_no_id = {
            "type": "text", "text": "No ID text",
            "x": 300, "y": 300,
        }
        elements = [shape, t_unrelated_no_id]
        sync_bound_text_translation(shape, elements, dx=50.0, dy=50.0)
        # Unrelated text without id must NOT be translated
        assert t_unrelated_no_id["x"] == 300.0
        assert t_unrelated_no_id["y"] == 300.0

    def test_compute_safe_arrow_endpoints_adaptive_padding(self):
        from services.diagram_base import compute_safe_arrow_endpoints
        # Shapes spaced far apart: distance between centers = 400
        s1 = _make_shape("s1", 100, 100, w=100, h=100)  # center (150, 150)
        s2 = _make_shape("s2", 500, 100, w=100, h=100)  # center (550, 150)
        start_x, start_y, end_x, end_y = compute_safe_arrow_endpoints(s1, s2)

        # Right edge of s1 is at x=200, left edge of s2 is at x=500
        # dot distance = 300 > 12.0, so adaptive padding is min(5.0, (300 - 2) / 2) = 5.0
        assert abs(start_x - 205.0) < 0.1
        assert abs(end_x - 495.0) < 0.1
        assert abs(start_y - 150.0) < 0.1
        assert abs(end_y - 150.0) < 0.1

    def test_compute_safe_arrow_endpoints_close_proximity(self):
        from services.diagram_base import compute_safe_arrow_endpoints
        # Shapes very close together: gap = 10px (0 < dot <= 12)
        s1 = _make_shape("s1", 100, 100, w=100, h=100)  # center (150, 150), right edge x=200
        s2 = _make_shape("s2", 210, 100, w=100, h=100)  # center (260, 150), left edge x=210
        start_x, start_y, end_x, end_y = compute_safe_arrow_endpoints(s1, s2)

        # gap dot = 10 <= 12, so no padding applied, preventing inverted arrow
        assert abs(start_x - 200.0) < 0.1
        assert abs(end_x - 210.0) < 0.1

    def test_compute_safe_arrow_endpoints_overlap(self):
        from services.diagram_base import compute_safe_arrow_endpoints
        # Overlapping shapes
        s1 = _make_shape("s1", 100, 100, w=100, h=100)  # center (150, 150)
        s2 = _make_shape("s2", 120, 100, w=100, h=100)  # center (170, 150), boundary dot < 0
        start_x, start_y, end_x, end_y = compute_safe_arrow_endpoints(s1, s2)

        # Fallback to centers
        assert abs(start_x - 150.0) < 0.1
        assert abs(end_x - 170.0) < 0.1


# ── Matrix Layout Tests ───────────────────────────────────────────

class TestMatrixLayout:
    def test_empty_returns_false(self):
        from core.layouts.matrix_layout import apply_matrix_layout
        assert apply_matrix_layout([]) is False

    def test_matrix_2x2_quadrant_positioning(self):
        from core.layouts.matrix_layout import apply_matrix_layout
        elements = [
            _make_shape("q_tl", 0, 0),
            _make_shape("q_tr", 0, 0),
            _make_shape("q_bl", 0, 0),
            _make_shape("q_br", 0, 0),
        ]
        assert apply_matrix_layout(elements, style="cross") is True

        shapes = {e["id"]: e for e in elements if e.get("type") in ("rectangle", "ellipse", "diamond")}
        assert len(shapes) == 4

        # Verify 2x2 grid distribution: 2 top, 2 bottom, 2 left, 2 right
        top_nodes = [s for s in shapes.values() if (s["y"] + s["height"] / 2) < 400.0]
        bottom_nodes = [s for s in shapes.values() if (s["y"] + s["height"] / 2) > 400.0]
        left_nodes = [s for s in shapes.values() if (s["x"] + s["width"] / 2) < 600.0]
        right_nodes = [s for s in shapes.values() if (s["x"] + s["width"] / 2) > 600.0]

        assert len(top_nodes) == 2
        assert len(bottom_nodes) == 2
        assert len(left_nodes) == 2
        assert len(right_nodes) == 2

        # Background crosshair lines should be inserted
        bg_lines = [e for e in elements if "matrix_v_" in e.get("id", "") or "matrix_h_" in e.get("id", "")]
        assert len(bg_lines) == 2

    def test_matrix_axis_style(self):
        from core.layouts.matrix_layout import apply_matrix_layout
        elements = [
            _make_shape("s1", 0, 0),
            _make_shape("s2", 0, 0),
        ]
        assert apply_matrix_layout(elements, style="axis") is True
        axis_lines = [e for e in elements if "axis_y_" in e.get("id", "") or "axis_x_" in e.get("id", "")]
        assert len(axis_lines) == 2

    def test_matrix_idempotency(self):
        from core.layouts.matrix_layout import apply_matrix_layout
        elements = [
            _make_shape("s1", 0, 0),
            _make_shape("s2", 0, 0),
        ]
        apply_matrix_layout(elements, style="cross")
        bg_lines_1 = [e for e in elements if "matrix_v_" in e.get("id", "") or "matrix_h_" in e.get("id", "")]
        assert len(bg_lines_1) == 2

        # Re-running layout should not duplicate dividers
        apply_matrix_layout(elements, style="cross")
        bg_lines_2 = [e for e in elements if "matrix_v_" in e.get("id", "") or "matrix_h_" in e.get("id", "")]
        assert len(bg_lines_2) == 2


# ── Value Chain Margin Tests ──────────────────────────────────────

class TestValueChainMargin:
    def test_last_node_without_margin_keyword_stays_rectangle(self):
        from core.layouts.value_chain_layout import apply_value_chain_layout
        elements = _chain_elements(4)
        apply_value_chain_layout(elements)
        last_node = next(e for e in elements if e["id"] == "v3")
        # Should stay rectangle because it does not have margin keywords
        assert last_node["type"] == "rectangle"

    def test_last_node_with_margin_keyword_converts_to_diamond(self):
        from core.layouts.value_chain_layout import apply_value_chain_layout
        elements = _chain_elements(4)
        elements.append({
            "id": "t_v3",
            "type": "text",
            "containerId": "v3",
            "text": "Biên lợi nhuận (Margin)",
            "x": 0, "y": 0,
        })
        apply_value_chain_layout(elements)
        last_node = next(e for e in elements if e["id"] == "v3")
        assert last_node["type"] == "diamond"


# ── Diagram Base & Worker Tests ───────────────────────────────────

class TestDiagramBaseAndWorker:
    def test_find_diagram_context_with_pipe(self):
        from services.diagram_base import find_diagram_context
        text = "Leading text. " * 50 + "![[he_thong.excalidraw.md|800x600]]" + " Trailing text." * 50
        ctx = find_diagram_context("he_thong.excalidraw.md", text)
        assert "![[he_thong.excalidraw.md|800x600]]" in ctx

    def test_find_diagram_context_fallback_to_heading(self):
        from services.diagram_base import find_diagram_context
        text = "Preamble content.\n\n## Kiến Trúc Hệ Thống Tổng Thể\nDetailed architecture section text here.\n\n## Next Chapter"
        ctx = find_diagram_context("kien_truc_he_thong.mermaid.md", text)
        assert "## Kiến Trúc Hệ Thống Tổng Thể" in ctx
        assert "Detailed architecture section text here." in ctx

    def test_mermaid_academic_theme_guard_non_flowchart(self):
        from services.mermaid_worker import _apply_academic_theme_to_mermaid
        pie_code = 'pie title Market Share\n  "Apple" : 45\n  "Google" : 55'
        themed = _apply_academic_theme_to_mermaid(pie_code)
        assert "classDef" not in themed
        assert "class " not in themed

    def test_mermaid_subgraph_styling_and_label_wrapping(self):
        from services.mermaid_worker import _apply_academic_theme_to_mermaid
        raw_code = (
            "flowchart TD\n"
            "  subgraph SG1[Nhóm Chức Năng]\n"
            "    A[Khái niệm phân tích dữ liệu rất dài cần bẻ dòng tự động] --> B[Đích Đến]\n"
            "  end"
        )
        themed = _apply_academic_theme_to_mermaid(raw_code)
        # Subgraph should have style, not class standard
        assert "style SG1 fill:#f8fafc,stroke:#334155,stroke-width:1px;" in themed
        assert "class SG1 standard;" not in themed
        # Node label should be wrapped with <br>
        assert "<br>" in themed

    def test_find_diagram_context_path_prefix_and_highest_scoring_heading(self):
        from services.diagram_base import find_diagram_context
        text = (
            "# Document\n\n"
            "## Giới thiệu tổng quan hệ thống\n"
            "Overview section text.\n\n"
            "## Chi tiết kiến trúc hệ thống dữ liệu lớn\n"
            "Deep architecture section text that matches all keywords.\n\n"
            "## Kết luận\n"
            "End text."
        )
        # 1. Path prefix normalization
        text_with_pipe = "Some text ![[kien_truc.excalidraw.md|800]] trailing"
        ctx_pipe = find_diagram_context("03 - Resources/attachments/kien_truc.excalidraw.md", text_with_pipe)
        assert "![[kien_truc.excalidraw.md|800]]" in ctx_pipe

        # 2. Highest scoring heading selection
        ctx_heading = find_diagram_context(
            "kien_truc_he_thong_du_lieu_lon.mermaid.md",
            text,
        )
        assert "## Chi tiết kiến trúc hệ thống dữ liệu lớn" in ctx_heading

    def test_mermaid_shape_preservation(self):
        from services.mermaid_worker import _apply_academic_theme_to_mermaid
        raw_code = (
            "flowchart TD\n"
            "  A([Stadium Start]) --> B[(Database Storage)]\n"
            "  B --> C((Circle Center))\n"
            "  C --> D{{Hexagon Process}}\n"
            "  D --> E(Rounded Node)\n"
            "  E --> F{Decision Node}"
        )
        themed = _apply_academic_theme_to_mermaid(raw_code)
        # Delimiters must be strictly preserved
        assert 'A(["Stadium Start"])' in themed
        assert 'B[("Database Storage")]' in themed
        assert 'C(("Circle Center"))' in themed
        assert 'D{{"Hexagon Process"}}' in themed
        assert 'E("Rounded Node")' in themed
        assert 'F{"Decision Node"}' in themed
        # Must not corrupt cylinder to rectangle with unicode parens
        assert "\u2768" not in themed

    def test_mermaid_chained_and_labeled_arrows_and_undirected(self):
        from services.mermaid_worker import _apply_academic_theme_to_mermaid
        raw_code = (
            "flowchart TD\n"
            "  HUB --- C1\n"
            "  HUB --- C2\n"
            "  HUB --- C3\n"
            "  C1 --> C2 --> C3 --> C1\n"
            "  C1 -->|success| S1[Success Target]\n"
            "  C2 -.->|optional| AUX[Auxiliary Target]"
        )
        themed = _apply_academic_theme_to_mermaid(raw_code)
        # HUB should be principal due to high connectivity (3 spokes)
        assert "class HUB principal;" in themed
        # AUX should be auxiliary due to dashed arrow -.->
        assert "class AUX auxiliary;" in themed
        # S1 should be standard
        assert "class S1 standard;" in themed
        # All cycle nodes must have class assignments
        assert "class C1 standard;" in themed
        assert "class C2 standard;" in themed
        assert "class C3 standard;" in themed


def test_sync_bound_text_translation_with_container_header_of():
    """sync_bound_text_translation must move text tagged with containerHeaderOf."""
    from services.diagram_base import sync_bound_text_translation

    container = {"id": "c1", "type": "rectangle", "x": 100.0, "y": 100.0, "boundElements": []}
    header_text = {"id": "t_hdr", "type": "text", "x": 100.0, "y": 114.0, "containerId": None, "containerHeaderOf": "c1"}
    elements = [container, header_text]

    sync_bound_text_translation(container, elements, 50.0, 30.0)
    assert header_text["x"] == 150.0
    assert header_text["y"] == 144.0


def test_normalize_canvas_bounding_box():
    """normalize_canvas_bounding_box must shift elements to safe positive coordinates >= (80, 60)."""
    from services.diagram_base import normalize_canvas_bounding_box

    elements = [
        {"id": "n1", "type": "rectangle", "x": -50.0, "y": -20.0},
        {"id": "n2", "type": "rectangle", "x": 100.0, "y": 200.0},
        {"id": "a1", "type": "arrow", "x": -50.0, "y": -20.0, "points": [[0.0, 0.0], [-10.0, -10.0]]}
    ]

    normalize_canvas_bounding_box(elements, min_padding_x=80.0, min_padding_y=60.0)
    # Arrow tip was at x = -60, y = -30. Shift should be: x + 140 -> 80, y + 90 -> 60
    assert elements[0]["x"] >= 80.0
    assert elements[0]["y"] >= 60.0
    assert elements[1]["x"] > 100.0


def test_layout_router_preserves_enclosing_containers():
    """apply_smart_layout must not flatten spatial layouts when enclosing containers exist."""
    from core.layout_router import apply_smart_layout

    # Container box enclosing child box
    container = {"id": "c1", "type": "rectangle", "x": 50.0, "y": 50.0, "width": 400.0, "height": 300.0}
    child = {"id": "ch1", "type": "rectangle", "x": 100.0, "y": 100.0, "width": 100.0, "height": 50.0}
    arrow = {"id": "a1", "type": "arrow", "x": 150.0, "y": 150.0, "points": [[0, 0], [50, 50]]}
    elements = [container, child, arrow]

    orig_c_x, orig_c_y = container["x"], container["y"]
    apply_smart_layout(elements)

    # Should not be reshuffled by Sugiyama
    assert container["x"] == orig_c_x
    assert container["y"] == orig_c_y


# --- Ticket 9: Responsive Diagrams for Mobile Tests ---

def test_mermaid_mobile_responsive_direction_normalization():
    """normalize_mermaid_direction must convert flowchart LR with >3 arrows to flowchart TD."""
    from services.mermaid_worker import normalize_mermaid_direction

    # <= 3 arrows: remains LR
    lr_short = "flowchart LR\n  A --> B\n  B --> C\n  C --> D"
    assert normalize_mermaid_direction(lr_short) == lr_short

    # > 3 arrows chained: switches to TD
    lr_chained = "flowchart LR\n  A --> B --> C --> D --> E"
    norm_chained = normalize_mermaid_direction(lr_chained)
    assert norm_chained.startswith("flowchart TD")

    # > 3 arrows separate lines: switches to TD
    lr_multiline = "flowchart LR\n  A --> B\n  B --> C\n  C --> D\n  D --> E"
    norm_multiline = normalize_mermaid_direction(lr_multiline)
    assert norm_multiline.startswith("flowchart TD")

    # Thick and dotted arrows counted
    lr_thick = "flowchart LR\n  A ==> B ==> C ==> D ==> E"
    norm_thick = normalize_mermaid_direction(lr_thick)
    assert norm_thick.startswith("flowchart TD")

    # Already TD: remains TD
    td_long = "flowchart TD\n  A --> B --> C --> D --> E"
    assert normalize_mermaid_direction(td_long) == td_long

    # Empty string handling
    assert normalize_mermaid_direction("") == ""

    # Quoted labels containing arrows do NOT falsely trigger TD
    lr_quoted_arrows = (
        'flowchart LR\n'
        '  Step1["Input --> Output"] --> Step2["Validation --> Confirmation"]'
    )
    assert normalize_mermaid_direction(lr_quoted_arrows) == lr_quoted_arrows

    # Comments containing arrows do NOT falsely trigger TD
    lr_comments_arrows = (
        "flowchart LR\n"
        "  %% A --> B --> C --> D\n"
        "  A --> B\n"
        "  B --> C"
    )
    assert normalize_mermaid_direction(lr_comments_arrows) == lr_comments_arrows

    # Dotted arrows with inline labels are counted correctly and trigger TD
    lr_dotted_labeled = (
        "flowchart LR\n"
        "  A -. bước 1 .-> B\n"
        "  B -. bước 2 .-> C\n"
        "  C -. bước 3 .-> D\n"
        "  D -. bước 4 .-> E"
    )
    norm_dotted = normalize_mermaid_direction(lr_dotted_labeled)
    assert norm_dotted.startswith("flowchart TD")

    # Solid arrows with inline text are counted correctly and trigger TD
    lr_text_labeled = (
        "flowchart LR\n"
        "  A -- gửi yêu cầu --> B\n"
        "  B -- xác thực --> C\n"
        "  C -- xử lý dữ liệu --> D\n"
        "  D -- phản hồi --> E"
    )
    norm_text = normalize_mermaid_direction(lr_text_labeled)
    assert norm_text.startswith("flowchart TD")


def test_mermaid_academic_theme_with_responsive_direction():
    """_apply_academic_theme_to_mermaid must normalize flowchart LR with >3 arrows to flowchart TD."""
    from services.mermaid_worker import _apply_academic_theme_to_mermaid

    raw_code = (
        "flowchart LR\n"
        "  Step1[Bắt đầu] --> Step2[Xử lý]\n"
        "  Step2 --> Step3[Đánh giá]\n"
        "  Step3 --> Step4[Phê duyệt]\n"
        "  Step4 --> Step5[Hoàn tất]"
    )
    themed = _apply_academic_theme_to_mermaid(raw_code)
    # Direction should be normalized to TD
    assert themed.startswith("flowchart TD")
    # Academic theme classes should still be declared and assigned
    assert "classDef principal" in themed
    assert "class Step1 principal;" in themed



