"""VvC Second Brain — Wiki Health: Domain Enricher.

Batch classifies un-tagged concepts into hierarchical canonical Grand Domains (v8.6 taxonomy)
via LLM, updating concept frontmatters and recording domain suggestions.
Part of Deep Module package services.wiki_health.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from core.config import cfg
from core.frontmatter import build_frontmatter, extract_body, parse_frontmatter
from core.llm import call_llm
from core.log import log
from .linter import VaultLinter

_logger = logging.getLogger("vvc.health.domain")

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


def _build_domain_prompt(title: str, summary: str) -> str:
    """Build classification prompt for domain tagging."""
    return (
        f"Hãy phân tích và phân loại khái niệm (Concept) sau vào ĐÚNG MỘT danh mục phân cấp (domain) phù hợp nhất.\n\n"
        f"Khái niệm:\n- Tiêu đề: {title}\n- Tóm tắt/Nội dung: {summary}\n\n"
        "Danh sách các phân cấp domain có sẵn:\n"
        "1. Tech & Science (Công nghệ & Khoa học):\n"
        "   - tech/ai: Trí tuệ nhân tạo, Học máy, LLM, Agents, Neural Networks.\n"
        "   - tech/computing: Hạ tầng tính toán, phần cứng, hệ điều hành, mạng máy tính.\n"
        "   - tech/security: Bảo mật, an ninh mạng, mã hóa dữ liệu.\n"
        "   - tech/software: Kỹ nghệ phần mềm, kiến trúc hệ thống, ngôn ngữ lập trình.\n"
        "   - tech/data: Khoa học dữ liệu, cơ sở dữ liệu, phân tích số liệu.\n"
        "2. Business & Management (Kinh doanh & Quản trị):\n"
        "   - business/strategy: Chiến lược kinh doanh, mô hình doanh nghiệp, định vị thị trường.\n"
        "   - business/leadership: Kỹ năng lãnh đạo, dẫn dắt đội ngũ, quản trị tổ chức.\n"
        "   - business/hr: Quản trị nguồn nhân lực, văn hóa doanh nghiệp, tuyển dụng, đãi ngộ.\n"
        "   - business/marketing: Marketing, thương hiệu, phễu bán hàng, hành vi khách hàng.\n"
        "   - business/finance: Tài chính doanh nghiệp, đầu tư, kế toán, dòng tiền.\n"
        "3. Cognitive & Human (Nhận thức & Phát triển con người):\n"
        "   - cognitive/psychology: Tâm lý học hành vi, nhận thức con người, thiên kiến.\n"
        "   - cognitive/philosophy: Triết học, tư duy hệ thống, tư duy phản biện, đạo đức học.\n"
        "   - cognitive/learning: Phương pháp học tập, giáo dục, tư duy mở (growth mindset).\n"
        "   - cognitive/decision: Lý thuyết ra quyết định, giải quyết vấn đề, đàm phán.\n"
        "   - cognitive/communication: Nghệ thuật truyền thông, thuyết trình, viết lách, thuyết phục.\n"
        "4. Innovation & Productivity (Đổi mới & Hiệu suất):\n"
        "   - innovation/design: Tư duy thiết kế (Design Thinking), phát triển và đổi mới sản phẩm.\n"
        "   - innovation/process: Quản trị quy trình, Lean, Agile, tối ưu vận hành.\n"
        "   - innovation/creativity: Tư duy sáng tạo, phát minh, giải pháp đột phá.\n"
        "   - productivity/personal: Hiệu suất cá nhân, quản lý thời gian, ghi chú Zettelkasten.\n"
        "   - productivity/collaboration: Làm việc nhóm, công cụ cộng tác, quản lý dự án.\n\n"
        "Quy tắc nghiêm ngặt: Trả về DUY NHẤT mã domain từ danh sách trên (ví dụ: 'tech/ai' hoặc 'business/strategy'), không viết thêm bất kỳ từ nào khác, không dùng dấu ngoặc kép."
    )


class DomainEnricher:
    """Batch classifies un-tagged concepts into canonical domains."""

    def __init__(self, concepts: list[dict] | None = None):
        """Initialize enricher with optional pre-loaded concepts to save IO."""
        if concepts is not None:
            self.concepts = concepts
        else:
            self.concepts = VaultLinter().concepts

    def _enrich_single_concept(self, c: dict) -> bool:
        """Classify and tag a single concept."""
        title = c.get("title", c["_stem"])
        summary = c.get("summary", "")
        prompt = _build_domain_prompt(title, summary)
        result = call_llm(prompt, task="correction", allowed_shorts=tuple(CANONICAL_DOMAINS))
        if not result:
            return False

        domain = re.sub(r"[^a-z\-/]", "", result.strip().lower().replace(" ", "-"))
        if domain in CANONICAL_DOMAINS:
            self._update_concept_tag(c["_path"], f"domain/{domain}")
            return True
        if len(domain) > 2 and domain not in ["yes", "no", "true", "false", "none", "null"]:
            self._record_domain_suggestion(c, domain)
        return False

    def enrich(self, batch_size: int = 20) -> int:
        untagged = [c for c in self.concepts if not any(
            t.startswith("domain/") for t in c.get("tags", [])
        )]
        if not untagged:
            return 0

        batch = untagged[:batch_size]
        enriched = sum(1 for c in batch if self._enrich_single_concept(c))
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


def enrich_domains(batch_size: int = 20, concepts: list[dict] | None = None) -> int:
    """Batch classify un-tagged concepts into canonical domains (Facade pattern)."""
    return DomainEnricher(concepts=concepts).enrich(batch_size)


__all__ = [
    "CANONICAL_DOMAINS",
    "DomainEnricher",
    "enrich_domains",
]
