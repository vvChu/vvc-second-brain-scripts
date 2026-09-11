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


def test_safe_write_text(tmp_path):
    """Test _safe_write_text avoids redundant writes when content is unchanged."""
    from wiki_maintain import _safe_write_text

    target = tmp_path / "test_moc.md"
    content = "# Test MOC Content\n"

    # First write: creates file
    assert _safe_write_text(target, content) is True
    assert target.exists()
    assert target.read_text(encoding="utf-8") == content

    # Second write with identical content: should skip write
    assert _safe_write_text(target, content) is False

    # Third write with modified content: should write
    new_content = "# Updated MOC Content\n"
    assert _safe_write_text(target, new_content) is True
    assert target.read_text(encoding="utf-8") == new_content


def test_clean_source_reference():
    """Test clean_source_reference extracts clean stems from various wikilink formats."""
    from services.moc_mermaid import clean_source_reference, flatten_source_list

    assert clean_source_reference("[[2024-01-01_Book_Title|Custom Title]]") == "2024-01-01_Book_Title"
    assert clean_source_reference("[[2024-01-01_Book_Title]]") == "2024-01-01_Book_Title"
    assert clean_source_reference("2024-01-01_Book_Title.md") == "2024-01-01_Book_Title"
    assert clean_source_reference("2024-01-01_Book_Title") == "2024-01-01_Book_Title"

    nested = ["[[source_a|Title A]]", ["source_b.md", "[[source_c]]"]]
    flattened = flatten_source_list(nested)
    assert flattened == ["source_a", "source_b", "source_c"]


def test_domain_aliases_and_grand_domains():
    """Test DOMAIN_ALIASES mapping and GRAND_DOMAINS taxonomy coverage."""
    from wiki_maintain import DOMAIN_ALIASES, GRAND_DOMAINS

    assert DOMAIN_ALIASES["ai"] == "artificial_intelligence"
    assert DOMAIN_ALIASES["hr"] == "human_resources"
    assert DOMAIN_ALIASES["phat_trien_ban_than"] == "personal_development"

    # Ensure Grand Domains contain all expected top-level highways
    assert "tech" in GRAND_DOMAINS
    assert "cognition" in GRAND_DOMAINS
    assert "business" in GRAND_DOMAINS
    assert "management" in GRAND_DOMAINS
    assert "society_science" in GRAND_DOMAINS


def test_vault_mtime_cache_helpers(tmp_path, monkeypatch):
    """Test scan_all_concepts and update_concept_cache with persistent caching."""
    import dataclasses
    from core.config import cfg
    from core.vault import scan_all_concepts, update_concept_cache

    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir(parents=True)
    state_dir = tmp_path / ".state"
    state_dir.mkdir(parents=True)

    mock_cfg = dataclasses.replace(cfg, concepts_dir=concepts_dir, state_dir=state_dir)
    monkeypatch.setattr("core.vault.cfg", mock_cfg)
    monkeypatch.setattr("core.vault._CONCEPTS_CACHE_FILE", state_dir / "_vault_concepts_cache.json")

    # Create a test concept file
    note1 = concepts_dir / "test_note_1.md"
    note1.write_text(
        "---\n"
        "title: 'Test Note 1'\n"
        "tags: ['domain/ai']\n"
        "source: '[[book_one|Book One]]'\n"
        "---\n\n"
        "Evidence Hook.\n"
        "Reference to [[other_note]].\n",
        encoding="utf-8"
    )

    # First scan: populates cache
    res1 = scan_all_concepts()
    assert len(res1) == 1
    assert res1[0]["_stem"] == "test_note_1"
    assert "other_note" in res1[0]["_links"]

    # Second scan: loads from cache
    res2 = scan_all_concepts()
    assert len(res2) == 1
    assert res2[0]["_stem"] == "test_note_1"
    assert "other_note" in res2[0]["_links"]
    assert "book_one" in res2[0]["_links"]

    # Test update_concept_cache
    updated = update_concept_cache(note1)
    assert updated is not None
    assert updated["_stem"] == "test_note_1"


def test_rebuild_incremental(tmp_path, monkeypatch):
    """Test rebuild_incremental updates source MOC and Master Index."""
    import dataclasses
    from core.config import cfg
    from wiki_maintain import rebuild_incremental

    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir(parents=True)
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir(parents=True)
    moc_dir = tmp_path / "moc"
    moc_dir.mkdir(parents=True)
    state_dir = tmp_path / ".state"
    state_dir.mkdir(parents=True)
    index_file = moc_dir / "index.md"

    mock_cfg = dataclasses.replace(
        cfg,
        concepts_dir=concepts_dir,
        sources_dir=sources_dir,
        moc_dir=moc_dir,
        state_dir=state_dir,
        index_file=index_file,
    )
    monkeypatch.setattr("core.vault.cfg", mock_cfg)
    monkeypatch.setattr("wiki_maintain.cfg", mock_cfg)
    monkeypatch.setattr("core.vault._CONCEPTS_CACHE_FILE", state_dir / "_vault_concepts_cache.json")
    monkeypatch.setattr("core.vault._SOURCES_CACHE_FILE", state_dir / "_vault_sources_cache.json")

    # Create source note
    src_file = sources_dir / "2026-01-01_Book_One.md"
    src_file.write_text(
        "---\n"
        "title: 'Book One'\n"
        "aliases: ['Book One']\n"
        "---\n\n"
        "# Book One\n",
        encoding="utf-8",
    )

    # Create concept note
    note_file = concepts_dir / "my_concept.md"
    note_file.write_text(
        "---\n"
        "title: 'My Concept'\n"
        "tags: ['domain/ai']\n"
        "source: '2026-01-01_Book_One.md'\n"
        "---\n\n"
        "> Evidence hook.\n\n"
        "## Core Idea\nExplanation.\n",
        encoding="utf-8",
    )

    rebuild_incremental(note_file)

    # Verify Source MOC was created
    moc_file = moc_dir / "sources" / "MOC_Book_One.md"
    assert moc_file.exists()
    moc_content = moc_file.read_text(encoding="utf-8")
    assert "My Concept" in moc_content
    assert "[[my_concept|My Concept]]" in moc_content

    # Verify Master Index was created
    assert index_file.exists()
    index_content = index_file.read_text(encoding="utf-8")
    assert "My Concept" in index_content


def test_rebuild_incremental_domain_moc(tmp_path, monkeypatch):
    """Test incremental rebuild triggers Domain MOC generation when threshold is met."""
    import dataclasses
    from core.config import cfg
    from wiki_maintain import rebuild_incremental

    moc_dir = tmp_path / "00 - Maps of Content"
    moc_dir.mkdir(parents=True, exist_ok=True)
    concepts_dir = tmp_path / "04 - Permanent" / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    sources_dir = tmp_path / "04 - Permanent" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    state_dir = tmp_path / "scripts" / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    index_file = moc_dir / "index.md"

    mock_cfg = dataclasses.replace(
        cfg,
        concepts_dir=concepts_dir,
        sources_dir=sources_dir,
        moc_dir=moc_dir,
        state_dir=state_dir,
        index_file=index_file,
    )
    monkeypatch.setattr("core.vault.cfg", mock_cfg)
    monkeypatch.setattr("wiki_maintain.cfg", mock_cfg)
    monkeypatch.setattr("core.vault._CONCEPTS_CACHE_FILE", state_dir / "_vault_concepts_cache.json")
    monkeypatch.setattr("core.vault._SOURCES_CACHE_FILE", state_dir / "_vault_sources_cache.json")

    # Create source note
    src_file = sources_dir / "2026-01-01_AI_Source.md"
    src_file.write_text(
        "---\ntitle: 'AI Source'\naliases: ['AI Source']\n---\n",
        encoding="utf-8",
    )

    # Create 15 concepts with tag domain/ai (alias for artificial_intelligence)
    last_note = None
    for i in range(15):
        c_file = concepts_dir / f"concept_{i}.md"
        c_file.write_text(
            f"---\ntitle: 'Concept {i}'\ntags: ['domain/ai']\nsource: '2026-01-01_AI_Source.md'\n---\n> Quote\n## Core Idea\nText\n",
            encoding="utf-8",
        )
        last_note = c_file

    # Rebuild incrementally with the 15th concept
    rebuild_incremental(last_note)

    # Verify Domain MOC was created with normalized alias in domains/
    domain_moc = moc_dir / "domains" / "Domain_Artificial_Intelligence.md"
    assert domain_moc.exists()
    content = domain_moc.read_text(encoding="utf-8")
    assert "Domain: Artificial Intelligence" in content
    assert "Concept 14" in content


