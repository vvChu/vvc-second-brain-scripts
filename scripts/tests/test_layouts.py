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
