# 🧠 VvC Second Brain — GitHub Copilot Instructions

Guidelines for GitHub Copilot when interacting with or writing code for the **VvC Second Brain** repository.

> **Constitution (SSoT)**: [`AGENTS.md`](file:///home/vvc/VvC_Notes/AGENTS.md)  
> **Living Architecture Reference**: [`.md/vault_mental_model_and_architecture.md`](file:///home/vvc/VvC_Notes/.md/vault_mental_model_and_architecture.md)  
> **SSoT Workspace Context**: [`.md/workspace_context.yaml`](file:///home/vvc/VvC_Notes/.md/workspace_context.yaml)  
> **Master Canonical Topic Note**: [[kien_truc_va_mental_model_vvc_second_brain|04 - Permanent/topics/kien_truc_va_mental_model_vvc_second_brain.md]]  
> **System Architecture Diagram (16:9)**: [[vvc_second_brain_architecture.excalidraw.md|03 - Resources/attachments/vvc_second_brain_architecture.excalidraw.md]]

---

## 1. Mental Model & Core Architecture (LLM Compiler Pattern)

The system operates as an Autonomous Knowledge Operating System ("Zero-Touch" LLM OS) following the **LLM Compiler Pattern** (Andrej Karpathy, 2026):
- **Role separation**: Humans are the *Source Provider* (photos of highlighted book pages, YouTube videos, podcasts, fleeting notes in `Brain_Dump.md`), while AI agents and background daemons act as the *Compiler & Librarian*.
- **3 Architectural Breakthroughs**:
  1. *Verifiable Ground Truth RAG*: Direct chapter-scoped BM25 lookup against the English book corpus, enforcing an **Evidence Hook (VN)** + **Ground Truth Verbatim (EN)** pair on every Concept Note.
  2. *Noise Gating & Anti-Resurrection*: Cognitive filtering `_is_meaningful_dump`, byte-offset state tracking (`.dump_state.json`), and URL deduplication (`.processed_urls.json`).
  3. *Closed-Loop Compounding Feedback*: In-depth answers in `Command.md` ($\ge 2500$ characters) compound into permanent Topic Notes (`04 - Permanent/topics/`), enriching future RAG queries.

---

## 2. 8 Living Architecture Pillars (Seams Map)

| Pillar | Technical Responsibility | Primary Files / Deep Seams |
| :--- | :--- | :--- |
| **P1. Operations & Single Runner** | Process coordination, split-brain protection, locks | `scripts/daemon.py`, `scripts/core/file_lock.py` |
| **P2. Storage Tiering** | Rclone VFS mount, local state/logs isolation | `scripts/config.yaml`, `scripts/.state/`, `scripts/logs/` |
| **P3. Knowledge Kernel** | Canonical v8.3 Concept Notes, Multi-Evidence Hooks, Pruning | `scripts/core/frontmatter.py`, `scripts/core/prompts/pipeline.py` |
| **P4. Compilation Pipeline** | 5-stage pipeline: OCR $\rightarrow$ BM25 $\rightarrow$ Synthesis $\rightarrow$ Self-Correction $\rightarrow$ Merger | `scripts/pipeline/image_processor.py`, `scripts/pipeline/ground_truth.py` |
| **P5. Multi-Channel Ingestion** | YouTube 4-tier Native ASR, Podcast Faster-Whisper, Command JIT | `scripts/services/youtube/`, `scripts/services/command/` |
| **P6. Adaptive AI Grid** | 4-tier routing, Circuit Breaker 503, WinError 206 stdin stream, CLI artifact | `scripts/core/llm/` |
| **P7. Artifacts Coordination** | Lazy ArtifactEngine, 16:9 Excalidraw, Mermaid 4 Patterns | `scripts/services/worker_dispatcher.py`, `.agents/rules/diagramming_hygiene.md` |
| **P8. Self-Healing Loops** | Semantic Merger (Cosine $\ge 0.88$), 2-tier Mtime, Sleep Consolidation | `scripts/pipeline/semantic_merger.py`, `scripts/sleep.py` |

---

## 3. Mandatory Operational Invariants

1. **Active-Passive Single-Active Runner**: Server Spark Linux (`spark-CCBA aarch64`, `100.83.192.30`) runs 24/7 Primary (`vvc-daemon.service`). Windows is Client-only (Obsidian UI). Never run concurrent daemons across hosts to avoid Google Drive Split-Brain.
2. **Stale Daemon Invariant**: Python loads code into RAM upon startup. When editing `scripts/` or `scripts/config.yaml`, ALWAYS restart running daemons using `scripts/.venv/bin/python scripts/daemon.py --restart` before verification.
3. **Visual Ergonomics (v8.15.10)**:
   - Diagrams with $\ge 3$ layers or $\ge 9$ nodes MUST use Excalidraw 16:9 (`![[...excalidraw.md|100%]]`) with a Markdown Architecture Specification Matrix table.
   - Small diagrams ($\le 8$ nodes) use Mermaid Academic Grayscale with pipe syntax `===>|"label"|` and Unicode operators (`≥`, `≤`).
4. **Clean Wikilinks & Zero-Code-Pill**: Never wrap wikilinks with backticks (`[[link]]`). In Markdown tables, escape the pipe (`[[slug\|alias]]`).
5. **Strict HTML Entity Context Isolation**: `#40;` và `#41;` are ONLY allowed inside ````mermaid` blocks. Outside mermaid, standard parentheses `()` must be used.
6. **Architectural Budgets & Zero-Slack Ratchets (v8.15.13)**: New production Python files must be $\le 350$ lines; new functions must be $\le 50$ lines (AST analysis). 5 legacy logic files and 60 legacy function files are locked with zero-slack ratchets (`test_architectural_budgets.py`).
7. **Session Artifact Buffer (.md/scratch/)**: All transient agent artifacts (plans, tasks, walkthroughs, claim notices) MUST be stored in `.md/scratch/` to avoid dirtying git working tree.

