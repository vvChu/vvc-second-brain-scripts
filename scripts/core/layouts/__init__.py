"""Layout engine package for Excalidraw deterministic diagram rendering.

Available engines:
  - sugiyama: Layered hierarchical (Sugiyama) layout
  - radial: Hub-and-spoke radial layout
  - cycle: Circular/cycle layout
  - matrix: 2x2 quadrant / axis scatter layout
  - concentric: Concentric circles layout
  - tree: Top-down or left-to-right tree layout
  - value_chain: Horizontal value-chain flow layout

All engines share the same interface::

    def apply_<name>_layout(elements: list[dict], **kwargs) -> bool:
        ...

They modify Excalidraw element dicts in-place and return True on success.
"""

from core.layouts.sugiyama_layout import apply_sugiyama_layout
from core.layouts.radial_layout import apply_radial_layout
from core.layouts.cycle_layout import apply_cycle_layout
from core.layouts.matrix_layout import apply_matrix_layout
from core.layouts.concentric_layout import apply_concentric_layout
from core.layouts.tree_layout import apply_tree_layout
from core.layouts.value_chain_layout import apply_value_chain_layout

__all__ = [
    "apply_sugiyama_layout",
    "apply_radial_layout",
    "apply_cycle_layout",
    "apply_matrix_layout",
    "apply_concentric_layout",
    "apply_tree_layout",
    "apply_value_chain_layout",
]
