# 🧠 VvC Second Brain — Project Context (v8.12.4)

> [!NOTE] Context File Hierarchy
> | File | Role | Authority |
> |:---|:---|:---|
> | `AGENTS.md` | **Constitution** — full rules, schemas, behavior | Highest |
> | `GEMINI.md` | **This file** — quick reference & entry point | Medium |
> | `scripts/GEMINI.md` | **Pipeline Override** — daemon text-processing mode | Scoped |
> | `CHANGELOG.md` | **Version history** — changelog only | Reference |
>
> **Rule**: `AGENTS.md` is the source of truth. Do NOT redefine rules here.

## Overview

Personal knowledge management system ("Second Brain") built on Obsidian. Autonomous ingestion pipeline following the **LLM Compiler Pattern** (Karpathy, 2026).

- **Philosophy**: AI agents = **librarians & compilers**. Human = **source provider**.
- **Core Pattern**: Raw images/books/URLs → OCR → Ground Truth RAG → Atomic Concept Synthesis → Zettelkasten.
- **Current version**: v8.12.4 — See `CHANGELOG.md` for full history.

## Directory Structure

| Path | Purpose |
|---|---|
| `00 - Maps of Content/` | 🗺️ MOC pages & Master Index |
| `03 - Resources/books/` | 📥 Input: new books (EPUB/PDF) |
| `04 - Permanent/` | 🧠 Compiled knowledge (concepts, sources & topics) |
| `05 - Fleeting/` | 📸 Active ingestion workspace |
| `99 - Archive/` | 🗄️ Processed raw materials (WebP compressed) |
| `scripts/` | ⚙️ Python automation pipeline |

## Key Commands

| Task | Command |
|---|---|
| **Main Pipeline** | `pythonw scripts/daemon.py` |
| **Book Watcher** | `pythonw scripts/book_ingest.py` |
| **Web Clipper** | `python scripts/web_clip.py "https://url"` |
| **Wiki Maintenance** | `python scripts/wiki_maintain.py` |
| **Weekly Consolidation** | `python scripts/sleep.py` |
| **EPUB Converter** | `python scripts/epub_convert.py <epub_path>` |

*Use `.venv\Scripts\activate` first. Use `pythonw` for headless daemons. `run_watcher.vbs` auto-launches via Task Scheduler.*

## Quick Rules (Details in AGENTS.md)

- **File Access**: Read-only `03 - Resources/`, `99 - Archive/`, `AGENTS.md`. Write to `04 - Permanent/`, `00 - Maps of Content/`, `05 - Fleeting/`.
- **Naming**: Concepts = `snake_case.md`. Sources = `YYYY-MM-DD_Title_Author.md`. MOCs = `MOC_Title.md`.
- **YAML Schema**: See `AGENTS.md` §3. Required fields include `source_page/chapter`, `ground_truth_page/chapter`, `people`, `companies`, `status`.
- **Concept Note Format** (v8.3): Evidence Hook (VN) → Citation Line → `## Core Idea` → `## 📖 Ground Truth` (EN) → `---` → `## References`.
- **Quality Gate**: 5 pre-save checks in `post_process.py`. Failed notes are rejected, never saved.
- **Research Discipline**: Double-Pass Adversarial Review required before proposing changes. See `AGENTS.md` §7.
- **Topic Backlog**: When asked to write new articles or brainstorm topics, always refer to the existing backlog of potential ideas at [[y_tuong_bai_viet_tiem_nang|Danh Mục Các Bài Viết Tiềm Năng]].

