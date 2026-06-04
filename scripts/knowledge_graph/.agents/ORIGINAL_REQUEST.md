# Original User Request

## Initial Request — 2026-06-04T12:47:22+07:00

An interactive semantic knowledge graph visualization tool for the VvC Second Brain workspace. It parses markdown files to extract metadata and wiki-links, then renders an interactive HTML/JS graph visualization.

Working directory: d:/VvC_Notes/scripts/knowledge_graph/
Integrity mode: demo

## Requirements

### R1. Metadata & Link Parser
Implement a parser that scans all markdown files in the following directories under `d:/VvC_Notes/`:
- `04 - Permanent/concepts/`
- `04 - Permanent/sources/` (root-level `.md` files only)
- `04 - Permanent/sources/transcripts/`
- `04 - Permanent/topics/`

Exclude non-markdown content (e.g., `04 - Permanent/sources/assets/`).

For each file, extract:
- YAML frontmatter fields: `title`, `aliases`, `tags`, `type`, `source`, `related`, `summary`
- The `related` field contains a mix of wiki-link format (`'[[target]]'`) and plain-text slugs (`target_name`) — the parser must normalize both into consistent node references.
- Note body: wiki-links in both formats `[[target_note]]` and `[[target_note|Display Alias]]` (pipe-separated alias syntax).
- Save or expose this parsed node-edge structure (the method of storage/exposure is decided by the team).

### R2. Interactive Graph Visualization Interface
Develop a premium responsive HTML/CSS/JS frontend to render the extracted graph:
- Color-code or shape-code nodes to visually distinguish between Concepts, Sources, and Topics.
- Support zooming, panning, drag-to-rearrange, and node selection.
- Clicking a node must display its details (title, type, summary/snippet, tags, and incoming/outgoing connections) in an overlay or interactive sidebar.

### R3. Search & Filter Controls
Provide interactive UI controls to query the graph:
- Full-text search to locate nodes by title, alias, or tags.
- Tag and type filters to hide/show nodes dynamically on the graph.

## Verification Plan

### Automated Verification Script
Implement a verification script `verify_graph.py` that reads the graph data source and asserts:
- **Node count**: Total nodes equals the total number of `.md` files across the four target directories.
- **Edge extraction**: Edges capture frontmatter `source`, `related` (both wiki-link and plain-text formats), and body `[[wiki-links]]` (both `[[target]]` and `[[target|alias]]` variants).
- **Schema compliance**: The output data format (JSON or equivalent) matches a defined schema with required fields: `id`, `title`, `type`, `tags`, `edges`.

### Visual Quality Review
- The frontend page must load successfully in a local browser without any JS errors in the console.

## Acceptance Criteria

### Data Integrity & Linking
- [ ] Total node count in the graph data matches the total `.md` file count across the four target directories (currently ~2,232 files).
- [ ] Nodes are labeled with their YAML `title` and typed correctly (`concept`, `source`, `topic`).
- [ ] Edges include both YAML `related` references and body wiki-links.

### Interactive UI
- [ ] Visual distinction between node types is immediately clear (different colors/shapes).
- [ ] Sidebar or overlay details display accurately when a node is clicked.
- [ ] Zoom, pan, and search functionality work smoothly without freezing the browser (2000+ nodes).
- [ ] The graph renders completely within 5 seconds of page load in a modern browser.

### Verification
- [ ] The automated test script `verify_graph.py` runs successfully and reports compliance with node count and edge extraction requirements.
