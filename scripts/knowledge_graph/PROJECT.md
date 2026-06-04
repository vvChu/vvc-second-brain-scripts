# Project: Interactive Semantic Knowledge Graph Visualization

## Architecture

### Overview
A 3-component tool that parses Obsidian vault markdown files, extracts metadata + wiki-links into a JSON graph, and renders an interactive HTML/JS visualization.

### Data Flow
```
Markdown Files (4 dirs, ~2232 files)
    → parse_graph.py (Python parser)
    → graph_data.json (JSON node-edge structure)
    → index.html + style.css + graph.js (Browser visualization)
    → verify_graph.py (Automated verification)
```

### Target Directories (under d:/VvC_Notes/)
1. `04 - Permanent/concepts/` — 2094 .md files (type: concept)
2. `04 - Permanent/sources/` — 7 root-level .md files only (type: source)
3. `04 - Permanent/sources/transcripts/` — 123 .md files (type: source/transcript)
4. `04 - Permanent/topics/` — 8 .md files (type: topic)

**Exclusions**: `04 - Permanent/sources/assets/` and any non-.md files

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Python Parser | parse_graph.py + graph_data.json | none | PLANNED |
| 2 | Frontend Visualization | index.html + style.css + graph.js | M1 (JSON schema) | PLANNED |
| 3 | Verification Script | verify_graph.py | M1 (JSON output) | PLANNED |

## Interface Contracts

### JSON Schema (graph_data.json)
```json
{
  "metadata": {
    "generated_at": "ISO-8601 timestamp",
    "vault_root": "d:/VvC_Notes/",
    "total_nodes": 2232,
    "total_edges": "<calculated>"
  },
  "nodes": [
    {
      "id": "alexnet_tac_dong_lich_su",
      "title": "AlexNet và tác động lịch sử",
      "type": "concept",
      "tags": ["knowledge", "type/concept", "domain/ai"],
      "aliases": ["AlexNet", "Deep Learning breakthrough"],
      "summary": "AlexNet là kiến trúc mạng thần kinh...",
      "source": "2026-05-12_the_thinking_machine_jensen_hu_stephen_witt",
      "file_path": "04 - Permanent/concepts/alexnet_tac_dong_lich_su.md"
    }
  ],
  "edges": [
    {
      "source": "alexnet_tac_dong_lich_su",
      "target": "dnnresearch",
      "type": "related"
    },
    {
      "source": "alexnet_tac_dong_lich_su",
      "target": "2026-05-12_the_thinking_machine_jensen_hu_stephen_witt",
      "type": "source_ref"
    },
    {
      "source": "alexnet_tac_dong_lich_su",
      "target": "chien_thang_tai_imagenet_2012",
      "type": "wiki_link"
    }
  ]
}
```

### Node ID Convention
- `id` = filename stem (without `.md` extension)
- For sources: `2026-05-12_the_thinking_machine_jensen_hu_stephen_witt`
- For concepts: `alexnet_tac_dong_lich_su`
- For topics: `ai_friendly_codebase`

### Edge Types
1. `related` — from YAML `related` field (both `[[wiki-link]]` and plain-text slug)
2. `source_ref` — from YAML `source` field (links concept → source note)
3. `wiki_link` — from body `[[target]]` or `[[target|alias]]` (excluding already-captured related/source)

### Node Type Assignment
- Files in `concepts/` → `"concept"`
- Files in `sources/` (root) → `"source"`
- Files in `sources/transcripts/` → `"source"` (subtype transcript, but type="source" for graph)
- Files in `topics/` → `"topic"`

### Related Field Normalization
The `related` field in YAML contains mixed formats:
- `'[[dnnresearch]]'` → extract `dnnresearch`
- `'[[chien_thang_tai_imagenet_2012]]'` → extract `chien_thang_tai_imagenet_2012`
- `han_che_kien_truc_cpu` → use as-is (plain text slug)
- `'[[target|Display Name]]'` → extract `target`

### Body Wiki-Link Extraction
Regex: `\[\[([^\]|]+)(?:\|[^\]]+)?\]\]`
- `[[target_note]]` → `target_note`
- `[[target_note|Display Alias]]` → `target_note`
- Normalize: strip `concepts/` prefix if present (e.g., `concepts/alex_krizhevsky` → `alex_krizhevsky`)

## Code Layout
All deliverables in `d:/VvC_Notes/scripts/knowledge_graph/`:
```
knowledge_graph/
├── parse_graph.py        ← M1: Markdown parser
├── graph_data.json       ← M1: Generated graph data
├── index.html            ← M2: Main visualization page
├── style.css             ← M2: Styles
├── graph.js              ← M2: Graph rendering logic
├── verify_graph.py       ← M3: Verification script
└── .agents/              ← Agent metadata (not source code)
```

## Performance Requirements
- Graph must render within 5 seconds with ~2232 nodes
- Recommended: Use WebGL-based renderer (e.g., force-graph library via CDN)
- Implement level-of-detail: hide labels at low zoom, show on hover/zoom
- Consider node clustering or canvas rendering for performance
