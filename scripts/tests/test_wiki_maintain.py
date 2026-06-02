"""Unit tests for services.moc_mermaid module (Mermaid Graph layout & caps)."""

import sys
from pathlib import Path

# Add scripts folder to path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from services.moc_mermaid import (
    _get_node_label_and_indicator,
    _calculate_dynamic_caps,
    generate_mermaid_flowchart,
    _mermaid_flat_overview,
)

def test_get_node_label_and_indicator():
    """Test status icons, confidence markers, wrapping, and sanitization in labels."""
    # 1. Seed status and high confidence (default)
    concept_seed = {
        "_stem": "test_seed",
        "title": "Khai niem ve hat giong",
        "status": "seed",
        "confidence": "high"
    }
    label = _get_node_label_and_indicator(concept_seed)
    assert label.startswith("🌱")
    assert "Khai niem" in label
    assert "🔍" not in label

    # 2. Growing status and low confidence
    concept_growing = {
        "_stem": "test_growing",
        "title": "Mo hinh dang phat trien",
        "status": "growing",
        "confidence": "low"
    }
    label = _get_node_label_and_indicator(concept_growing)
    assert label.startswith("🌿")
    assert label.endswith("🔍")

    # 3. Evergreen status and medium confidence
    concept_evergreen = {
        "_stem": "test_evergreen",
        "title": "Cay thuong xanh co xua",
        "status": "evergreen",
        "confidence": "medium"
    }
    label = _get_node_label_and_indicator(concept_evergreen)
    assert label.startswith("🌳")
    assert label.endswith("🔍")

    # 4. Long title truncation
    concept_long = {
        "_stem": "test_long",
        "title": "Title " + "x" * 60,
        "status": "seed",
        "confidence": "high"
    }
    label = _get_node_label_and_indicator(concept_long, max_title_len=30)
    assert "..." in label
    assert len(label.replace("<br>", " ")) < 60


def test_calculate_dynamic_caps():
    """Test dynamic limits determination based on density ratio R."""
    stems = {"a", "b", "c", "d", "e", "f"}
    
    # 1. Dense graph: 6 nodes, 10 edges (R = 10 / 6 = 1.67 >= 1.5)
    dense_edges = [
        ("a", "b"), ("a", "c"), ("a", "d"), ("a", "e"),
        ("b", "c"), ("b", "d"), ("b", "f"),
        ("c", "d"), ("c", "e"), ("d", "f")
    ]
    max_nodes, max_edges = _calculate_dynamic_caps(dense_edges, stems)
    assert max_nodes == 12
    assert max_edges == 18

    # 2. Moderate graph: 6 nodes, 7 edges (R = 7 / 6 = 1.17 => 1.0 <= R < 1.5)
    mod_edges = [
        ("a", "b"), ("a", "c"), ("b", "d"), ("c", "e"), ("d", "f"), ("e", "f"), ("a", "f")
    ]
    max_nodes, max_edges = _calculate_dynamic_caps(mod_edges, stems)
    assert max_nodes == 18
    assert max_edges == 25

    # 3. Sparse graph: 6 nodes, 5 edges (R = 5 / 6 = 0.83 < 1.0)
    sparse_edges = [
        ("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"), ("e", "f")
    ]
    max_nodes, max_edges = _calculate_dynamic_caps(sparse_edges, stems)
    assert max_nodes == 25
    assert max_edges == 35


def test_generate_mermaid_flowchart_orphan_pruning():
    """Test generate_mermaid_flowchart with high density, verifying dynamic caps and orphan pruning."""
    # Group of 6 concepts with connections
    concepts = [
        {"_stem": "concept_a", "title": "Concept A", "status": "seed", "confidence": "high", "related": ["concept_b", "concept_c"]},
        {"_stem": "concept_b", "title": "Concept B", "status": "growing", "confidence": "low", "related": ["concept_d"]},
        {"_stem": "concept_c", "title": "Concept C", "status": "evergreen", "confidence": "high", "related": ["concept_d"]},
        {"_stem": "concept_d", "title": "Concept D", "status": "evergreen", "confidence": "medium", "related": ["concept_e"]},
        {"_stem": "concept_e", "title": "Concept E", "status": "seed", "confidence": "high", "related": ["concept_f"]},
        {"_stem": "concept_f", "title": "Concept F", "status": "seed", "confidence": "high", "related": []},
        # Disconnected concept
        {"_stem": "concept_orphan", "title": "Orphan Concept", "status": "seed", "confidence": "high", "related": []}
    ]
    
    flowchart = generate_mermaid_flowchart(concepts)
    
    # Verify the flowchart generated
    assert "flowchart TD" in flowchart
    assert "classDef default" in flowchart
    
    # Verify nodes are decorated and styled
    assert "🌱 Concept A" in flowchart
    assert "🌿 Concept B" in flowchart
    assert "🌳 Concept C" in flowchart
    assert "🔍" in flowchart  # Concept B and D are low/medium confidence, should have 🔍
    
    # Verify orphan is pruned
    assert "concept_orphan" not in flowchart


def test_mermaid_flat_overview():
    """Test _mermaid_flat_overview generates correct undirected graph with dynamic caps."""
    concepts = [
        {"_stem": "a", "title": "Node A", "status": "seed", "confidence": "high", "related": ["b", "c"]},
        {"_stem": "b", "title": "Node B", "status": "seed", "confidence": "high", "related": ["c"]},
        {"_stem": "c", "title": "Node C", "status": "seed", "confidence": "high", "related": ["d"]},
        {"_stem": "d", "title": "Node D", "status": "seed", "confidence": "high", "related": []},
    ]
    
    graph = _mermaid_flat_overview(concepts)
    
    assert "flowchart LR" in graph
    # Check undirected edges
    assert " --- " in graph
    assert "Node A" in graph
    assert "Node B" in graph
    assert "Node C" in graph
    assert "Node D" in graph
