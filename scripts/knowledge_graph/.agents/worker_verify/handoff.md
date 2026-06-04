# Handoff — verify_graph.py (M3: Verification Script)

## Observation

1. **PROJECT.md** at `d:/VvC_Notes/scripts/knowledge_graph/PROJECT.md` (123 lines) defines:
   - JSON schema with `metadata`, `nodes[]`, `edges[]`
   - Node fields: `id`, `title`, `type`, `tags`, `aliases`, `summary`, `source`, `file_path`
   - Edge fields: `source`, `target`, `type` (enum: `related`, `source_ref`, `wiki_link`)
   - 4 target directories with expected counts: concepts=2094, sources=7, transcripts=123, topics=8 → total 2232

2. **Actual file counts** (verified via PowerShell `Measure-Object`):
   - `04 - Permanent/concepts/*.md` → 2094
   - `04 - Permanent/sources/*.md` (root only) → 7
   - `04 - Permanent/sources/transcripts/*.md` → 123
   - `04 - Permanent/topics/*.md` → 8
   - Total: 2232 ✅ matches PROJECT.md

3. **No subdirectories** exist inside `concepts/`, `topics/`, or `transcripts/` — confirmed via `find_by_name`. This means `rglob("*.md")` is safe (won't double-count).

4. **Sample concept file** (`alexnet_tac_dong_lich_su.md`) confirmed YAML structure:
   - `related:` field contains mixed formats (`'[[slug]]'` and plain `slug`)
   - `source:` field contains filename with `.md` extension
   - Body contains `[[wiki-links]]` and `[[link|alias]]` format
   - Files use Windows `\r\n` line endings — parser handles this via `.rstrip()` and `\n` search

## Logic Chain

1. Script needs to validate `graph_data.json` against actual filesystem → must count files in 4 dirs independently.
2. Sources dir uses `recursive=False` to exclude `transcripts/` and `assets/` subdirs, while `transcripts/` is counted separately — prevents overlap.
3. Spot-check reads actual `.md` files, parses YAML with a stdlib-only parser, and cross-references against edges in the graph. This catches real discrepancies, not just structural issues.
4. Schema validation checks every node/edge against the enum constraints from PROJECT.md.
5. Terminal color support detected via `isatty()` with `FORCE_COLOR` env override.
6. Exit code follows convention: 0=pass, 1=fail (including missing `graph_data.json`).

## Caveats

- **Could not execute** the script because command approval timed out. Script correctness verified by code review and structural analysis only.
- The minimal YAML parser handles the common cases seen in this vault (scalar fields, list fields with `- item` syntax). It does NOT handle multi-line strings, nested objects, or flow sequences beyond `[]`. This is sufficient for the fields we need (`related`, `source`, `tags`).
- The `summary` field in YAML can span multiple lines (line 19-20 in sample) — the parser treats continuation lines as separate keys, but this doesn't affect verification since we only check `related` and `source`.

## Conclusion

`verify_graph.py` has been created at `d:/VvC_Notes/scripts/knowledge_graph/verify_graph.py` (485 lines). It implements all 3 verification checks:
1. **Node count** — compares `len(nodes)` vs actual `.md` file count across 4 directories
2. **Edge extraction** — counts per-type + spot-checks 10 random nodes against their source files
3. **Schema compliance** — validates required fields and enum constraints for every node and edge

The script is runnable standalone. Before `graph_data.json` exists, it reports a clear error with instructions. After the parser generates the JSON, running `python verify_graph.py` produces a formatted report with color output and correct exit code.

## Verification Method

```bash
# Activate venv first
cd d:/VvC_Notes/scripts/knowledge_graph

# Test 1: Run without graph_data.json (should print helpful error, exit 1)
python verify_graph.py
echo $LASTEXITCODE   # expect 1

# Test 2: After parse_graph.py generates graph_data.json:
python verify_graph.py
echo $LASTEXITCODE   # expect 0 if graph is valid

# Test 3: Corrupt graph_data.json to test failure paths
# e.g., remove a node, change an edge type to "invalid"
```

## Files Modified/Created
- `d:/VvC_Notes/scripts/knowledge_graph/verify_graph.py` — **NEW** — automated verification script (stdlib-only, 485 lines)
