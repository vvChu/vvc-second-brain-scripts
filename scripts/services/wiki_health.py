"""VvC Second Brain — Wiki Health Service (v7.0).

Consolidated: Lint + Heal + Dedup + Domain Enrichment.

Usage:
    from services.wiki_health import lint_vault, heal_broken_links, enrich_domains
    report = lint_vault()
    heal_broken_links()
    enrich_domains()
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import TypedDict, Dict, List

from core.config import cfg
from core.frontmatter import (
    parse_frontmatter, 
    normalize_stem, 
    build_concept_frontmatter, 
    extract_body, 
    build_frontmatter
)
from core.llm import call_llm
from core.log import log
from core.vault import scan_all_concepts, scan_all_sources

_logger = logging.getLogger("vvc.health")

# ============================================================
# Types & Constants
# ============================================================

class LintReport(TypedDict, total=False):
    orphans: List[str]
    broken_links: List[Dict[str, str]]
    missing_frontmatter: List[Dict[str, List[str]]]
    duplicates: List[List[str]]
    bridge_candidates: List[str]
    tag_clusters: Dict[str, int]
    total_concepts: int
    broken_body_links: List[Dict[str, str]]
    prospective_related_seeds: List[Dict[str, str]]
    code_pill_wikilinks: List[Dict[str, Any]]

_CODE_PILL_LINK_PATTERN = re.compile(r"`(!?\[\[[^`\n]+?\]\])`")

_REJECT_PATTERNS = [
    re.compile(r"^\d{4}$"),           # Years like "2012"
    re.compile(r"^[A-Z]{1,3}$"),     # Abbreviations like "AI"
    re.compile(r"^Ví dụ$"),           # Generic terms
    re.compile(r"^Chương \d+"),       # Chapter names
    re.compile(r"^\d+$"),             # Pure numbers
    re.compile(r"^(tab|fig|img)\d+(_\d+)?$"),
    re.compile(r"^\d+_.*(note|chapter|footnote).*$", re.IGNORECASE),
    re.compile(r"^p\d+_ch\d+.*", re.IGNORECASE),          # Page/Chapter artifacts (e.g. p000_ch13)
    re.compile(r".*_(jpg|jpeg|png|pdf)$", re.IGNORECASE), # File extensions as stems
]

CANONICAL_DOMAINS = [
    # Legacy domains for backwards compatibility (DO NOT REMOVE)
    "ai", "business", "computing", "culture", "education",
    "hr", "innovation", "leadership", "management",
    "philosophy", "productivity", "psychology", "strategy", "technology",
    
    # Hierarchical domains v8.6
    "tech/ai", "tech/computing", "tech/security", "tech/software", "tech/data",
    "business/strategy", "business/leadership", "business/hr", "business/marketing", "business/finance",
    "cognitive/psychology", "cognitive/philosophy", "cognitive/learning", "cognitive/decision", "cognitive/communication",
    "innovation/design", "innovation/process", "innovation/creativity", "productivity/personal", "productivity/collaboration"
]

_LINK_PATTERN = re.compile(r"\[\[([^\]|]+)")
MEDIA_EXTENSIONS = {".webp", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf", ".mp3", ".mp4"}

# ============================================================
# Core Classes
# ============================================================

class VaultLinter:
    """Handles 6 health checks for the vault using a single-pass optimized strategy."""
    
    def __init__(self):
        self.concepts = scan_all_concepts()
        
        # Ensure _links is populated (cached by scan_all_concepts)
        for c in self.concepts:
            if "_links" not in c:
                try:
                    content = c["_path"].read_text(encoding="utf-8")
                    c["_links"] = _LINK_PATTERN.findall(content)
                except OSError:
                    c["_links"] = []

        self.existing_stems = {normalize_stem(c["_stem"]) for c in self.concepts}
        for c in self.concepts:
            aliases = c.get("aliases")
            if isinstance(aliases, list):
                for alias in aliases:
                    if alias and isinstance(alias, str):
                        self.existing_stems.add(normalize_stem(alias))
                        
        # Load sources to prevent false broken links to source documents
        sources = scan_all_sources()
        for s in sources:
            self.existing_stems.add(normalize_stem(s["_stem"]))
            aliases = s.get("aliases")
            if isinstance(aliases, list):
                for alias in aliases:
                    if alias and isinstance(alias, str):
                        self.existing_stems.add(normalize_stem(alias))

        # Load MOC directory files to prevent false broken links to MOCs, Command, index, etc.
        for f in cfg.moc_dir.rglob("*.md"):
            self.existing_stems.add(normalize_stem(f.stem))

        # Load topic files to prevent false broken links to topics
        topics_dir = cfg.vault_root / "04 - Permanent" / "topics"
        if topics_dir.exists():
            for f in topics_dir.iterdir():
                if f.suffix == ".md":
                    self.existing_stems.add(normalize_stem(f.stem))

        # Load book corpus chapter files to prevent false broken links to source_chapter/ground_truth_chapter
        if cfg.resources_books_dir.exists():
            for f in cfg.resources_books_dir.rglob("*.md"):
                self.existing_stems.add(normalize_stem(f.stem))

        # Load fleeting notes to prevent false broken links to Brain_Dump, Command, etc.
        for fleeting_file in [cfg.dump_file, cfg.command_file]:
            if fleeting_file.exists():
                self.existing_stems.add(normalize_stem(fleeting_file.stem))

    def _evaluate_concept_metrics(
        self, 
        c: dict, 
        report: LintReport, 
        all_linked: set, 
        by_prefix: dict
    ) -> None:
        """Helper to process a single concept during linting."""
        stem = c["_stem"]
        
        # Check 1: Missing frontmatter (support both 'source' and 'sources' from merged notes)
        has_source = bool(c.get("source") or c.get("sources"))
        missing = [f for f in ["title", "type", "tags"] if not c.get(f)]
        if not has_source:
            missing.append("source")
        if missing:
            report["missing_frontmatter"].append({"file": stem, "missing": missing})
        
        # Check 2: Tag clusters
        for tag in c.get("tags", []):
            if tag.startswith("domain/"):
                report["tag_clusters"][tag] += 1
        
        # Check 3: Broken links (ignore media file attachments)
        rel_field = c.get("related", [])
        rel_str = " ".join(str(r) for r in rel_field) if isinstance(rel_field, list) else str(rel_field)

        for link in c.get("_links", []):
            lower_link = link.lower()
            if any(lower_link.endswith(ext) for ext in MEDIA_EXTENSIONS):
                continue
            normalized = normalize_stem(link)
            all_linked.add(normalized)
            if normalized not in self.existing_stems:
                is_frontmatter_related = link in rel_str or normalized in normalize_stem(rel_str)
                origin = "frontmatter_related" if is_frontmatter_related else "body"
                broken_item = {"from": stem, "to": link, "origin": origin}
                report["broken_links"].append(broken_item)
                if origin == "body":
                    report["broken_body_links"].append(broken_item)
                else:
                    report["prospective_related_seeds"].append(broken_item)
                
        # Check 4: Prefix for duplicates
        prefix = normalize_stem(c.get("title", ""))[:20]
        if prefix:
            by_prefix[prefix].append(stem)

        # Check 5: Code-pill wikilinks
        try:
            raw_content = c["_path"].read_text(encoding="utf-8")
            pills = _CODE_PILL_LINK_PATTERN.findall(raw_content)
            if pills:
                report["code_pill_wikilinks"].append({
                    "file": stem,
                    "type": "concept",
                    "count": len(pills),
                    "matches": pills,
                })
        except OSError:
            pass

    def lint(self) -> LintReport:
        report: LintReport = {
            "orphans": [],
            "broken_links": [],
            "missing_frontmatter": [],
            "duplicates": [],
            "bridge_candidates": [],
            "tag_clusters": defaultdict(int),
            "total_concepts": len(self.concepts),
            "broken_body_links": [],
            "prospective_related_seeds": [],
            "code_pill_wikilinks": [],
        }

        all_linked = set()
        by_prefix: dict[str, list] = defaultdict(list)

        # Single pass through all concepts
        for c in self.concepts:
            self._evaluate_concept_metrics(c, report, all_linked, by_prefix)

        # Ingest outgoing links from Maps of Content (MOCs), Sources, and Topics to eliminate False Orphans
        for moc_file in cfg.moc_dir.rglob("*.md"):
            if moc_file.name == "Weekly_Synthesis.md":
                continue
            try:
                content = moc_file.read_text(encoding="utf-8")
                for link in _LINK_PATTERN.findall(content):
                    all_linked.add(normalize_stem(link))
            except OSError:
                pass

        if cfg.sources_dir.exists():
            for src_file in cfg.sources_dir.rglob("*.md"):
                try:
                    content = src_file.read_text(encoding="utf-8")
                    for link in _LINK_PATTERN.findall(content):
                        all_linked.add(normalize_stem(link))
                except OSError:
                    pass

        topics_dir = cfg.vault_root / "04 - Permanent" / "topics"
        if topics_dir.exists():
            for topic_file in topics_dir.glob("*.md"):
                try:
                    content = topic_file.read_text(encoding="utf-8")
                    for link in _LINK_PATTERN.findall(content):
                        all_linked.add(normalize_stem(link))
                    pills = _CODE_PILL_LINK_PATTERN.findall(content)
                    if pills:
                        report["code_pill_wikilinks"].append({
                            "file": topic_file.stem,
                            "type": "topic",
                            "count": len(pills),
                            "matches": pills,
                        })
                except OSError:
                    pass

        # Check 5: Orphans (Post-pass evaluation)
        for c in self.concepts:
            stem_norm = normalize_stem(c["_stem"])
            if stem_norm not in all_linked and c.get("type") == "concept":
                if not c.get("related", []):
                    report["orphans"].append(c["_stem"])

        # Check 6: Populate duplicates
        for prefix, items in by_prefix.items():
            if len(items) > 1:
                report["duplicates"].append(items)

        _logger.info(
            f"Lint: {len(report['orphans'])} orphans, "
            f"{len(report['broken_links'])} broken links ({len(report['broken_body_links'])} in body, {len(report['prospective_related_seeds'])} in frontmatter), "
            f"{len(report['missing_frontmatter'])} missing FM"
        )
        log("lint", f"Health check: {report['total_concepts']} concepts scanned, {len(report['orphans'])} true orphans")
        return report


class LinkHealer:
    """Auto-creates quality stubs for broken wiki-links (Facade pattern)."""
    
    def __init__(self):
        import json
        self.rejected_file = cfg.state_dir / ".rejected_stubs.json"
        self.rejected_cache = set()
        if self.rejected_file.exists():
            try:
                self.rejected_cache = set(json.loads(self.rejected_file.read_text(encoding="utf-8")))
            except Exception:
                pass

        # Load Whitelist from config.yaml dynamically to keep it KISS!
        self.whitelisted_stubs = set()
        try:
            import yaml
            config_path = Path(__file__).parent.parent / "config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    raw_cfg = yaml.safe_load(f)
                    health_cfg = raw_cfg.get("health", {})
                    wl = health_cfg.get("whitelist_stubs", [])
                    if isinstance(wl, list):
                        self.whitelisted_stubs = {normalize_stem(item) for item in wl if isinstance(item, str)}
        except Exception as e:
            _logger.warning(f"Failed to load whitelist_stubs from config.yaml: {e}")

    def heal(self, report: LintReport, max_heal_limit: int = 15) -> int:
        import json
        import time
        broken = report.get("broken_links", [])
        if not broken:
            return 0

        # Deduplicate by target
        targets: dict[str, list[str]] = defaultdict(list)
        for entry in broken:
            targets[entry["to"]].append(entry["from"])

        # Sort targets by frequency descending (number of source documents linking to it)
        sorted_targets = sorted(targets.items(), key=lambda item: len(item[1]), reverse=True)

        # Apply batch limit
        if len(sorted_targets) > max_heal_limit:
            _logger.info(f"LinkHealer: Found {len(sorted_targets)} broken links. Limiting to top {max_heal_limit} most frequent targets to protect API.")
            sorted_targets = sorted_targets[:max_heal_limit]

        created = 0
        consecutive_errors = 0
        
        for target, sources in sorted_targets:
            # Heuristic pre-filter (Fast rejection without LLM)
            if self._heuristic_reject(target):
                self._unlink_in_sources(target, sources)
                continue

            # LLM Semantic Arbitrator (bypassed if target is whitelisted)
            norm_target = normalize_stem(target)
            if norm_target in getattr(self, "whitelisted_stubs", set()):
                _logger.info(f"Whitelisted stub approved directly: {target}")
                is_valid = True
            else:
                # Throttle to max 20 Requests Per Minute (RPM)
                time.sleep(3.0) 

                is_valid = self._is_valid_concept(target)
                if is_valid is None:
                    consecutive_errors += 1
                    _logger.debug(f"LLM API failure for: {target} ({consecutive_errors}/3). Backing off 30s...")
                    time.sleep(30)  # Long backoff to allow rate-limits to reset
                    if consecutive_errors >= 3:
                        _logger.error("Consecutive API failures reached 3. Aborting LinkHealer to protect API.")
                        break
                    continue
                
            # Reset error counter on success
            consecutive_errors = 0

            if not is_valid:
                _logger.debug(f"Rejected by LLM: {target}")
                self.rejected_cache.add(target)
                try:
                    self.rejected_file.write_text(json.dumps(list(self.rejected_cache)), encoding="utf-8")
                except OSError:
                    pass
                self._unlink_in_sources(target, sources)
                continue

            # Self-healing: if the approved concept was previously in rejected cache, remove it!
            if target in self.rejected_cache:
                self.rejected_cache.discard(target)
                _logger.info(f"Self-healed cache: removed whitelisted stub '{target}' from rejected stubs list.")
                try:
                    self.rejected_file.write_text(json.dumps(list(self.rejected_cache)), encoding="utf-8")
                except OSError:
                    pass

            # Create stub
            if self._create_stub(target, sources):
                created += 1

        if created:
            log("heal", f"Created {created} concept stubs")
        return created

    def _heuristic_reject(self, name: str) -> bool:
        """Fast rejection of invalid concepts without calling LLM."""
        norm_name = normalize_stem(name)
        if norm_name in getattr(self, "whitelisted_stubs", set()):
            _logger.info(f"Whitelisted stub (bypassing filters): {name}")
            return False

        if name in getattr(self, "rejected_cache", set()):
            _logger.debug(f"Rejected by cache (Strict Abort): {name}")
            return True
            
        if len(name) < 3:
            _logger.debug(f"Rejected by heuristic (too short): {name}")
            return True
            
        if len(name) > 60:
            _logger.debug(f"Rejected by heuristic (too long): {name}")
            return True
            
        # Reject if name contains no alphabetical characters
        if not re.search(r'[a-zA-Z]', name):
            _logger.debug(f"Rejected by heuristic (no letters): {name}")
            return True
            
        if any(pat.match(name) for pat in _REJECT_PATTERNS):
            _logger.debug(f"Rejected by pattern: {name}")
            return True
            
        return False

    def _is_valid_concept(self, name: str) -> bool | None:
        prompt = (
            f'Đây có phải là một KHÁI NIỆM cốt lõi có giá trị tri thức ĐỘC LẬP cực kỳ cao trong hệ thống Zettelkasten không?\n'
            f'Tên: "{name}"\n\n'
            f'Quy tắc nghiêm ngặt: Bạn là người gác cổng tri thức. Đừng dễ dãi! Chỉ tạo mới nếu nó thực sự là một khái niệm lớn. Nếu nghi ngờ hoặc khái niệm quá phụ, hoặc chỉ là từ vựng thông thường, CẦN TỪ CHỐI.\n'
            f'TUYỆT ĐỐI TỪ CHỐI: Các từ chỉ bảng biểu (table), hình ảnh (figure, img), ghi chú (note, footnote, chapter) hoặc cụm từ ngẫu nhiên bị cắt cụt do lỗi OCR.\n'
            f'Trả lời CHÍNH XÁC: "YES" hoặc "NO"\n'
            f'- YES nếu: Bạn tự tin 100% đây là một khái niệm học thuật cốt lõi (Core Concept), một mô hình tư duy lớn, hoặc framework quan trọng xứng đáng có một trang wiki dài 1000 từ để phân tích sâu sắc.\n'
            f'- NO nếu: Nó chỉ là một tính từ, một danh từ chỉ sự vật/hiện tượng thông thường, tên riêng, từ vựng phổ thông, cụm từ ghép ngẫu nhiên do văn nói, một ý tưởng vụn vặt, hoặc một thuật ngữ không có chiều sâu học thuật.\n'
        )
        result = call_llm(prompt, task="correction", strategy="round_robin")
        if not result:
            return None
        return result.strip().upper().startswith("YES")

    def manage_stub_lifecycle(self) -> dict[str, int]:
        """Scan all stubs, purge orphan stubs (those not linked by any high-quality concept or source),
        and record stale pending stubs (exists > 30 days) to a JSON file for Weekly Synthesis.
        
        Returns:
            Dict containing 'purged' count and 'stale' count.
        """
        import json
        from datetime import date, datetime
        from collections import defaultdict
        
        # 1. Scan concepts and sources using vault utilities
        concepts = scan_all_concepts()
        sources = scan_all_sources()
        
        # Identify stub concepts and gather their normalized stems
        stubs = []
        stub_stems = set()
        for c in concepts:
            is_stub = (c.get("confidence") == "low" and c.get("source_type") == "stub")
            if is_stub:
                stubs.append(c)
                stub_stems.add(normalize_stem(c["_stem"]))
                
        if not stubs:
            _logger.info("LinkHealer: No stub notes found in the vault.")
            return {"purged": 0, "stale": 0}
            
        # 2. Track incoming links to these stubs from high-quality nodes
        incoming_hq_links: dict[str, list[str]] = defaultdict(list)
        
        # Parse links from non-stub concepts (high-quality concepts)
        for c in concepts:
            stem_norm = normalize_stem(c["_stem"])
            if stem_norm in stub_stems:
                continue  # Skip stubs linking to stubs to prevent circular dependency keeps
                
            try:
                # Use _links cached in memory if available, otherwise parse file
                links = c.get("_links")
                if links is None:
                    content = c["_path"].read_text(encoding="utf-8")
                    links = _LINK_PATTERN.findall(content)
                    c["_links"] = links
                
                for link in links:
                    norm_link = normalize_stem(link)
                    if norm_link in stub_stems:
                        incoming_hq_links[norm_link].append(c["_stem"])
            except OSError:
                pass
                
        # Parse links from source notes (sources are always considered high-quality)
        for s in sources:
            try:
                content = s["_path"].read_text(encoding="utf-8")
                links = _LINK_PATTERN.findall(content)
                for link in links:
                    norm_link = normalize_stem(link)
                    if norm_link in stub_stems:
                        incoming_hq_links[norm_link].append(s["_stem"])
            except OSError:
                pass
                
        # 3. Purge Orphan Stubs
        purged_count = 0
        active_stubs = []
        for stub in stubs:
            norm_stem = normalize_stem(stub["_stem"])
            # An orphan stub is one with 0 incoming links from high-quality concepts or sources
            if not incoming_hq_links[norm_stem]:
                try:
                    stub["_path"].unlink()
                    _logger.info(f"[health] Purged orphan stub: {stub['_stem']}.md")
                    purged_count += 1
                except OSError as e:
                    _logger.warning(f"Failed to delete orphan stub {stub['_stem']}.md: {e}")
            else:
                active_stubs.append(stub)
                
        # 4. Check Stale Pending Stubs (> 30 days) among active stubs
        stale_count = 0
        stale_entries = []
        for stub in active_stubs:
            created_val = stub.get("date_created")
            created_date = None
            if created_val:
                if isinstance(created_val, str):
                    try:
                        created_date = date.fromisoformat(created_val)
                    except ValueError:
                        pass
                elif isinstance(created_val, (date, datetime)):
                    created_date = created_val if isinstance(created_val, date) else created_val.date()
            
            if created_date:
                age_days = (date.today() - created_date).days
                if age_days > 30:
                    stale_count += 1
                    stale_entries.append({
                        "stem": stub["_stem"],
                        "title": stub.get("title", stub["_stem"]),
                        "age_days": age_days,
                        "date_created": created_date.isoformat(),
                        "linked_from": incoming_hq_links[normalize_stem(stub["_stem"])][:3]
                    })
                    
        # 5. Record stale pending stubs to state directory for Weekly Synthesis
        if stale_entries:
            stale_file = cfg.state_dir / ".stale_stubs.json"
            try:
                stale_file.write_text(json.dumps(stale_entries, ensure_ascii=False, indent=2), encoding="utf-8")
                _logger.info(f"[health] Recorded {len(stale_entries)} stale pending stubs to {stale_file.name}")
            except Exception as e:
                _logger.warning(f"Failed to write stale stubs cache: {e}")
                
        return {"purged": purged_count, "stale": stale_count}

    def _create_stub(self, name: str, sources: list[str]) -> bool:
        filename = normalize_stem(name) + ".md"
        filepath = cfg.concepts_dir / filename

        if filepath.exists():
            return False

        fm = build_concept_frontmatter(
            name,
            source=[s + ".md" for s in sources] if len(sources) > 1 else (sources[0] + ".md" if sources else "web_imputed"),
            source_type="stub",
            summary=f"Auto-generated stub for broken link from: {', '.join(sources[:3])}",
            confidence="low",
        )

        body = f"\n> Stub — needs review and expansion.\n\n## Core Idea\n\n(Pending)\n\n## References\n\n"
        for src in sources[:5]:
            body += f"- Linked from: [[{src}]]\n"

        try:
            filepath.write_text(fm + body, encoding="utf-8")
            _logger.info(f"Stub created: {filename}")
            return True
        except OSError:
            return False

    def _unlink_in_sources(self, target: str, source_stems: list[str]) -> None:
        """Remove the wikilink brackets from the source documents for rejected concepts."""
        escaped_target = re.escape(target)
        # Matches [[target]] or [[target|alias]]
        pattern = re.compile(r'\[\[' + escaped_target + r'(?:\|([^\]]+))?\]\]', re.IGNORECASE)
        
        def replacer(match):
            # Return the alias if it exists, otherwise the target
            return match.group(1) if match.group(1) else target

        for src_stem in source_stems:
            src_file = cfg.concepts_dir / f"{src_stem}.md"
            if not src_file.exists():
                continue
                
            try:
                content = src_file.read_text(encoding="utf-8")
                new_content = pattern.sub(replacer, content)
                if new_content != content:
                    src_file.write_text(new_content, encoding="utf-8")
                    _logger.debug(f"Unlinked '{target}' in {src_stem}.md")
            except OSError as e:
                _logger.warning(f"Failed to unlink '{target}' in {src_stem}.md: {e}")



class DomainEnricher:
    """Batch classifies un-tagged concepts into canonical domains."""
    
    def __init__(self, concepts: list[dict] | None = None):
        """Initialize enricher with optional pre-loaded concepts to save IO."""
        if concepts is not None:
            self.concepts = concepts
        else:
            self.concepts = VaultLinter().concepts

    def enrich(self, batch_size: int = 20) -> int:
        untagged = [c for c in self.concepts if not any(
            t.startswith("domain/") for t in c.get("tags", [])
        )]

        if not untagged:
            return 0

        batch = untagged[:batch_size]
        enriched = 0

        for c in batch:
            title = c.get("title", c["_stem"])
            summary = c.get("summary", "")

            prompt = (
                f"Hãy phân tích và phân loại khái niệm (Concept) sau vào ĐÚNG MỘT danh mục phân cấp (domain) phù hợp nhất.\n\n"
                f"Khái niệm:\n"
                f"- Tiêu đề: {title}\n"
                f"- Tóm tắt/Nội dung: {summary}\n\n"
                f"Danh sách các phân cấp domain có sẵn:\n"
                f"1. Tech & Science (Công nghệ & Khoa học):\n"
                f"   - tech/ai: Trí tuệ nhân tạo, Học máy, LLM, Agents, Neural Networks.\n"
                f"   - tech/computing: Hạ tầng tính toán, phần cứng, hệ điều hành, mạng máy tính.\n"
                f"   - tech/security: Bảo mật, an ninh mạng, mã hóa dữ liệu.\n"
                f"   - tech/software: Kỹ nghệ phần mềm, kiến trúc hệ thống, ngôn ngữ lập trình.\n"
                f"   - tech/data: Khoa học dữ liệu, cơ sở dữ liệu, phân tích số liệu.\n"
                f"2. Business & Management (Kinh doanh & Quản trị):\n"
                f"   - business/strategy: Chiến lược kinh doanh, mô hình doanh nghiệp, định vị thị trường.\n"
                f"   - business/leadership: Kỹ năng lãnh đạo, dẫn dắt đội ngũ, quản trị tổ chức.\n"
                f"   - business/hr: Quản trị nguồn nhân lực, văn hóa doanh nghiệp, tuyển dụng, đãi ngộ.\n"
                f"   - business/marketing: Marketing, thương hiệu, phễu bán hàng, hành vi khách hàng.\n"
                f"   - business/finance: Tài chính doanh nghiệp, đầu tư, kế toán, dòng tiền.\n"
                f"3. Cognitive & Human (Nhận thức & Phát triển con người):\n"
                f"   - cognitive/psychology: Tâm lý học hành vi, nhận thức con người, thiên kiến.\n"
                f"   - cognitive/philosophy: Triết học, tư duy hệ thống, tư duy phản biện, đạo đức học.\n"
                f"   - cognitive/learning: Phương pháp học tập, giáo dục, tư duy mở (growth mindset).\n"
                f"   - cognitive/decision: Lý thuyết ra quyết định, giải quyết vấn đề, đàm phán.\n"
                f"   - cognitive/communication: Nghệ thuật truyền thông, thuyết trình, viết lách, thuyết phục.\n"
                f"4. Innovation & Productivity (Đổi mới & Hiệu suất):\n"
                f"   - innovation/design: Tư duy thiết kế (Design Thinking), phát triển và đổi mới sản phẩm.\n"
                f"   - innovation/process: Quản trị quy trình, Lean, Agile, tối ưu vận hành.\n"
                f"   - innovation/creativity: Tư duy sáng tạo, phát minh, giải pháp đột phá.\n"
                f"   - productivity/personal: Hiệu suất cá nhân, quản lý thời gian, ghi chú Zettelkasten.\n"
                f"   - productivity/collaboration: Làm việc nhóm, công cụ cộng tác, quản lý dự án.\n\n"
                f"Quy tắc nghiêm ngặt: Trả về DUY NHẤT mã domain từ danh sách trên (ví dụ: 'tech/ai' hoặc 'business/strategy'), không viết thêm bất kỳ từ nào khác, không dùng dấu ngoặc kép."
            )

            result = call_llm(prompt, task="correction", allowed_shorts=tuple(CANONICAL_DOMAINS))
            if not result:
                continue

            domain = result.strip().lower().replace(" ", "-")
            # Clean up the output to prevent random punctuation/junk, keeping slashes
            domain = re.sub(r"[^a-z\-/]", "", domain)
            if domain in CANONICAL_DOMAINS:
                self._update_concept_tag(c["_path"], f"domain/{domain}")
                enriched += 1
            elif len(domain) > 2 and domain not in ["yes", "no", "true", "false", "none", "null"]:
                # Record domain suggestions for Weekly Synthesis
                self._record_domain_suggestion(c, domain)

        if enriched:
            log("enrich", f"Tagged {enriched}/{len(batch)} concepts with domains")
        return enriched

    def _record_domain_suggestion(self, concept: dict, suggested_domain: str) -> None:
        """Record domain suggestions to a temporary JSON file for Weekly Synthesis."""
        suggestion_file = cfg.state_dir / ".domain_suggestions.json"
        suggestions = []
        if suggestion_file.exists():
            try:
                suggestions = json.loads(suggestion_file.read_text(encoding="utf-8"))
            except Exception:
                suggestions = []

        # Avoid duplicates
        exists = any(
            s.get("concept_stem") == concept["_stem"] and s.get("suggested_domain") == suggested_domain
            for s in suggestions
        )
        if not exists:
            suggestions.append({
                "concept_stem": concept["_stem"],
                "concept_title": concept.get("title", concept["_stem"]),
                "suggested_domain": suggested_domain,
                "summary": concept.get("summary", "")
            })
            try:
                suggestion_file.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
                _logger.info(f"[enrich] Recorded domain suggestion: '{suggested_domain}' for '{concept['_stem']}'")
            except Exception as e:
                _logger.warning(f"Failed to record domain suggestion: {e}")

    def _update_concept_tag(self, filepath: Path, new_tag: str) -> None:
        try:
            content = filepath.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            body = extract_body(content)

            tags = fm.get("tags", [])
            if new_tag not in tags:
                tags.append(new_tag)
                fm["tags"] = tags
                filepath.write_text(build_frontmatter(fm) + body, encoding="utf-8")
        except OSError as e:
            _logger.warning(f"Failed to update tag for {filepath.name}: {e}")


# ============================================================
# Procedural Exports (Backwards Compatibility)
# ============================================================

def lint_vault() -> LintReport:
    """Run 6 health checks on the vault (Facade pattern)."""
    return VaultLinter().lint()


def heal_broken_links(report: LintReport | None = None, max_heal_limit: int = 15) -> int:
    """Auto-create concept stubs for broken wiki-links and manage stub lifecycle (Facade pattern)."""
    if report is None:
        report = lint_vault()
    
    healer = LinkHealer()
    
    # Kích hoạt quản trị vòng đời stub (Purge orphans + Check stale)
    try:
        healer.manage_stub_lifecycle()
    except Exception as e:
        _logger.error(f"Stub lifecycle management failed: {e}")
        
    return healer.heal(report, max_heal_limit)


def enrich_domains(batch_size: int = 20, concepts: list[dict] | None = None) -> int:
    """Batch classify un-tagged concepts into canonical domains (Facade pattern)."""
    return DomainEnricher(concepts=concepts).enrich(batch_size)


def scan_wikilink_code_pills(fix: bool = False, target_dirs: list[Path] | None = None) -> list[dict[str, Any]]:
    """Scan vault files for code-pill wikilinks (`[[...]]` or `![[...]]`).
    
    If fix=True, removes backticks around wikilinks in-place.
    Returns a list of findings with file path, count, and matched strings.
    """
    findings = []
    pattern = _CODE_PILL_LINK_PATTERN
    if target_dirs is None:
        target_dirs = [
            cfg.concepts_dir,
            cfg.vault_root / "04 - Permanent" / "topics",
            cfg.sources_dir,
        ]
    for d in target_dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.md"):
            try:
                content = p.read_text(encoding="utf-8")
                matches = pattern.findall(content)
                if matches:
                    findings.append({
                        "file": str(p),
                        "count": len(matches),
                        "matches": matches,
                    })
                    if fix:
                        cleaned = pattern.sub(r"\1", content)
                        p.write_text(cleaned, encoding="utf-8")
                        _logger.info(f"Cleaned {len(matches)} code-pill wikilinks in {p.name}")
            except Exception as e:
                _logger.warning(f"Error scanning code-pills in {p.name}: {e}")
    return findings


class OrthographicHealer:
    """Checks and heals orthographic/homophone errors in concept titles."""
    
    def __init__(self, concepts: list[dict] | None = None):
        if concepts is not None:
            self.concepts = concepts
        else:
            self.concepts = VaultLinter().concepts

    def heal(self, batch_size: int = 20) -> int:
        # Sort concepts by date_modified descending
        sorted_concepts = sorted(
            self.concepts, 
            key=lambda c: str(c.get("date_modified", "")), 
            reverse=True
        )
        batch = sorted_concepts[:batch_size]
        healed_count = 0
        renames = {}  # {old_stem: (new_stem, correct_title, concept_dict)}

        for c in batch:
            title = c.get("title", c["_stem"])
            summary = c.get("summary", "")
            
            prompt = (
                f"Khái niệm sau đây có bị lỗi chính tả nghiêm trọng do nhầm lẫn đồng âm vùng miền (ví dụ: Tr/Ch, S/X, D/Gi/R) không?\n"
                f"Title: {title}\nSummary: {summary}\n\n"
                f"Trả về ĐÚNG 1 JSON object (KHÔNG giải thích thêm):\n"
                f"{{\"is_typo\": true/false, \"correct\": \"Tên Đúng (nếu có)\"}}\n"
            )
            
            result = call_llm(prompt, task="correction")
            if not result:
                continue
                
            try:
                match = re.search(r"\{.*?\}", result, re.DOTALL)
                if match:
                    ans = json.loads(match.group(0))
                    if ans.get("is_typo") and ans.get("correct"):
                        correct_title = ans["correct"].strip()
                        if correct_title.lower() != title.lower() and len(correct_title) > 2:
                            old_stem = c["_stem"]
                            new_stem = normalize_stem(correct_title)
                            if old_stem != new_stem:
                                renames[old_stem] = (new_stem, correct_title, c)
            except Exception as e:
                _logger.warning(f"OrthographicHealer failed parsing JSON: {e}")

        # Now apply all renames and collect actual successfully renamed stems
        successful_renames = {}
        for old_stem, (new_stem, correct_title, c) in renames.items():
            if self._apply_rename_only(c, correct_title, old_stem, new_stem):
                successful_renames[old_stem] = new_stem
                healed_count += 1

        # Perform Single-Pass Link Update across the entire vault
        if successful_renames:
            _update_all_links_vault_wide_batch(successful_renames)

        if healed_count:
            log("heal", f"OrthographicHealer fixed {healed_count} typos")
        return healed_count

    def _apply_rename_only(self, c: dict, correct_title: str, old_stem: str, new_stem: str) -> bool:
        """Rename the physical file and update frontmatter without updating wikilinks."""
        old_path: Path = c["_path"]
        new_path = old_path.parent / f"{new_stem}.md"
        
        try:
            content = old_path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            body = extract_body(content)
            
            fm["title"] = correct_title
            new_content = build_frontmatter(fm) + body
            
            new_path.write_text(new_content, encoding="utf-8")
            old_path.unlink()
            _logger.info(f"OrthographicHealer renamed: {old_stem} -> {new_stem}")
            return True
        except OSError as e:
            _logger.warning(f"Failed to rename file {old_stem}: {e}")
            return False


def _update_all_links_vault_wide_batch(renames: dict[str, str]) -> None:
    """Global find and replace for a batch of wikilinks in a single pass."""
    escaped_keys = [re.escape(k) for k in renames.keys()]
    pattern_str = rf"\[\[({'|'.join(escaped_keys)})([\|\]])"
    pattern = re.compile(pattern_str)

    def replacer(match):
        old_stem = match.group(1)
        new_stem = renames.get(old_stem, old_stem)
        suffix = match.group(2)
        return f"[[{new_stem}{suffix}"

    dirs_to_check = [cfg.concepts_dir, cfg.sources_dir, cfg.dump_file.parent]
    updated_files = 0
    total_files = 0

    for d in dirs_to_check:
        if not d.exists():
            continue
        for f in d.rglob("*.md"):
            total_files += 1
            try:
                text = f.read_text(encoding="utf-8")
                if pattern.search(text):
                    new_text = pattern.sub(replacer, text)
                    f.write_text(new_text, encoding="utf-8")
                    updated_files += 1
            except OSError as e:
                _logger.warning(f"Failed to read/write file {f.name} during batch link update: {e}")

    _logger.info(f"Batch Link Update complete: updated links in {updated_files}/{total_files} files.")


class TitleStandardizer:
    """Detects and standardizes raw, non-academic, or incorrectly formatted concept titles."""
    
    def __init__(self, concepts: list[dict] | None = None):
        if concepts is not None:
            self.concepts = concepts
        else:
            self.concepts = VaultLinter().concepts

    def standardize(self, batch_size: int = 15) -> int:
        from datetime import date
        non_standard = []
        for c in self.concepts:
            title = c.get("title", "")
            stem = c.get("_stem", "")
            
            # Kiểm tra các tiêu chuẩn thô
            is_bad = False
            if not title:
                is_bad = True
            elif "_" in title:
                is_bad = True
            elif stem != normalize_stem(title):
                is_bad = True
            
            if is_bad:
                non_standard.append(c)

        if not non_standard:
            return 0

        # Ưu tiên sửa đổi các file mới nhất
        sorted_non_standard = sorted(
            non_standard, 
            key=lambda x: str(x.get("date_modified", "")), 
            reverse=True
        )
        batch = sorted_non_standard[:batch_size]
        healed_count = 0
        renames = {}

        for c in batch:
            title = c.get("title", c["_stem"])
            stem = c["_stem"]
            summary = c.get("summary", "")

            prompt = (
                f"Hãy chuẩn hóa và Việt hóa tiêu đề thô sau đây thành một tiêu đề học thuật tiếng Việt cực kỳ chuẩn xác, chuyên nghiệp và có dấu (Title Case):\n"
                f"Tiêu đề thô: \"{title}\"\n"
                f"Tên tệp: \"{stem}\"\n"
                f"Mô tả khái niệm: \"{summary}\"\n\n"
                f"Quy tắc nghiêm ngặt:\n"
                f"1. Trả lời CHÍNH XÁC duy nhất tiêu đề mới đã chuẩn hóa (KHÔNG giải thích gì thêm, KHÔNG đặt trong dấu ngoặc kép).\n"
                f"2. Nếu tiêu đề gốc là tiếng Anh thô, hãy dịch sang thuật ngữ tiếng Việt học thuật chuẩn xác tương đương (song ngữ nếu cần thiết).\n"
                f"3. Loại bỏ toàn bộ các ký tự lỗi như gạch dưới, viết tắt thô sơ."
            )

            result = call_llm(prompt, task="correction", min_length=3)
            if not result:
                continue

            correct_title = result.strip().strip('"').strip("'")
            if correct_title.lower() != title.lower() and len(correct_title) > 2:
                old_stem = stem
                new_stem = normalize_stem(correct_title)
                if old_stem != new_stem:
                    if self._apply_rename_only(c, correct_title, old_stem, new_stem):
                        renames[old_stem] = new_stem
                        healed_count += 1
                else:
                    if self._apply_frontmatter_update_only(c, correct_title):
                        healed_count += 1

        if renames:
            _update_all_links_vault_wide_batch(renames)

        if healed_count:
            log("heal", f"TitleStandardizer standardized {healed_count} concept titles")
        return healed_count

    def _apply_rename_only(self, c: dict, correct_title: str, old_stem: str, new_stem: str) -> bool:
        """Rename physical file and update title/date_modified in frontmatter."""
        from datetime import date
        old_path: Path = c["_path"]
        new_path = old_path.parent / f"{new_stem}.md"
        
        try:
            content = old_path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            body = extract_body(content)
            
            fm["title"] = correct_title
            fm["date_modified"] = date.today()
            
            # Clean up redundant H1 header at the very beginning of the body if present
            cleaned_body = re.sub(r"^\s*#\s+.*?\n+", "", body)
            new_content = build_frontmatter(fm) + cleaned_body
            
            new_path.write_text(new_content, encoding="utf-8")
            old_path.unlink()
            _logger.info(f"TitleStandardizer renamed: {old_stem} -> {new_stem}")
            return True
        except OSError as e:
            _logger.warning(f"Failed to rename file {old_stem}: {e}")
            return False

    def _apply_frontmatter_update_only(self, c: dict, correct_title: str) -> bool:
        """Update only the title/date_modified in frontmatter, keeping the file name."""
        from datetime import date
        filepath: Path = c["_path"]
        
        try:
            content = filepath.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            body = extract_body(content)
            
            fm["title"] = correct_title
            fm["date_modified"] = date.today()
            
            # Clean up redundant H1 header at the very beginning of the body if present
            cleaned_body = re.sub(r"^\s*#\s+.*?\n+", "", body)
            new_content = build_frontmatter(fm) + cleaned_body
            
            filepath.write_text(new_content, encoding="utf-8")
            _logger.info(f"TitleStandardizer updated title in frontmatter: {c['_stem']} -> {correct_title}")
            return True
        except OSError as e:
            _logger.warning(f"Failed to update frontmatter for file {c['_stem']}: {e}")
            return False


def heal_orthography(batch_size: int = 20, concepts: list[dict] | None = None) -> int:
    """Batch heal orthographic typoes in concepts (Facade pattern)."""
    return OrthographicHealer(concepts=concepts).heal(batch_size)


def standardize_titles(batch_size: int = 15, concepts: list[dict] | None = None) -> int:
    """Batch standardize non-academic or poorly formatted concept titles (Facade pattern)."""
    return TitleStandardizer(concepts=concepts).standardize(batch_size)


# Re-export generate_weekly_synthesis from weekly_synthesis for backward compatibility
from services.weekly_synthesis import generate_weekly_synthesis

