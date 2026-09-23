"""Unit tests for core.markdown_sanitizer."""

from __future__ import annotations

import pytest
from core.markdown_sanitizer import (
    clean_wikilink_quotes,
    heal_artifact_embed_syntax,
    heal_html_entity_leakage,
    heal_mermaid_edge_syntax,
)


def test_clean_wikilink_quotes_basic():
    assert clean_wikilink_quotes('![["diagram.png"]]') == "![[diagram.png]]"
    assert clean_wikilink_quotes('![["diagram.png"|400]]') == "![[diagram.png|400]]"
    assert clean_wikilink_quotes("![['chart.svg']]") == "![[chart.svg]]"
    assert clean_wikilink_quotes('[["concept_note.md"]]') == "[[concept_note.md]]"
    assert clean_wikilink_quotes("[[note_without_quotes]]") == "[[note_without_quotes]]"


def test_clean_wikilink_quotes_code_pills():
    assert clean_wikilink_quotes("`[[concept_note|[1]]]`") == "[[concept_note|[1]]]"
    assert clean_wikilink_quotes("`[[slug]]`") == "[[slug]]"
    assert clean_wikilink_quotes("`![[image.png]]`") == "![[image.png]]"


def test_heal_artifact_embed_syntax():
    assert heal_artifact_embed_syntax("![[foo_excalidraw_md]]") == "![[foo.excalidraw.md]]"
    assert heal_artifact_embed_syntax("![[foo_excalidraw_md|100%]]") == "![[foo.excalidraw.md|100%]]"
    assert heal_artifact_embed_syntax("![[bar_mermaid_md|800]]") == "![[bar.mermaid.md|800]]"
    assert heal_artifact_embed_syntax("![[baz_d2_svg]]") == "![[baz.d2.svg]]"


def test_heal_mermaid_edge_syntax():
    # Forward thick edge
    res = heal_mermaid_edge_syntax('HUB ===="sync"====> SPOKE')
    assert res == 'HUB ===>|"sync"| SPOKE'

    # Dotted edge
    res = heal_mermaid_edge_syntax('SPOKE -."feedback".-> HUB')
    assert res == 'SPOKE -.->|"feedback"| HUB'

    # Bidirectional thick edge
    res = heal_mermaid_edge_syntax('A <===="sync"====> B')
    assert res == 'A <===>|"sync"| B'

    # Comparison operator normalization
    res = heal_mermaid_edge_syntax('A ===>|"score >= 0.88"| B')
    assert res == 'A ===>|"score ≥ 0.88"| B'

    res = heal_mermaid_edge_syntax('A ===>|"latency <= 50ms"| B')
    assert res == 'A ===>|"latency ≤ 50ms"| B'


def test_heal_html_entity_leakage():
    sample = """| Cột 1 | Cột 2 #40;Ghi chú#41; |
|---|---|
| Dữ liệu | Chi tiết #40;test#41; |

```mermaid
flowchart TD
    A["Node #40;Inside#41;"] ===="flow"====> B["End #40;OK#41;"]
```

Văn bản ngoài #40;ngoặc đơn#41;
"""
    cleaned = heal_html_entity_leakage(sample)
    # Outside mermaid: #40; and #41; become ( and )
    assert "| Cột 2 (Ghi chú) |" in cleaned
    assert "Chi tiết (test)" in cleaned
    assert "Văn bản ngoài (ngoặc đơn)" in cleaned

    # Inside mermaid: #40; and #41; are preserved, and edge syntax is healed
    assert 'A["Node #40;Inside#41;"] ===>|"flow"| B["End #40;OK#41;"]' in cleaned
