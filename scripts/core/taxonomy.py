"""VvC Second Brain — Grand Domain Taxonomy & Canonical Aliases.

Core taxonomy definitions and normalization utilities for vault knowledge organization.
Part of the core foundation layer (ADR-0044, ADR-0047).
"""

from __future__ import annotations

import functools
import unicodedata
from typing import Any

# Canonical taxonomy mapping to prevent domain fragmentation (v8.6+)
DOMAIN_ALIASES: dict[str, str] = {
    "ai": "artificial_intelligence",
    "hr": "human_resources",
    "phat_trien_ban_than": "personal_development",
    "organization_design": "organizational_design",
    "learning_methods": "learning_methodology",
    "business_management": "management",
    "quan_tri": "management",
    "quan_ly": "management",
    "chien_luoc": "strategy",
    "cong_nghe": "technology",
    "nhan_su": "human_resources",
    "nhan_thuc": "cognition",
    "tri_tue_nhan_tao": "artificial_intelligence",
    "tam_ly": "psychology",
    "triet_hoc": "philosophy",
    "giao_duc": "education",
    "phuong_phap_luan": "learning_methodology",
    "ban_hang": "business",
    "kinh_doanh": "business",
    "quan_tri_kinh_doanh": "business",
    "to_chuc": "organizational_design",
    "quan_tri_to_chuc": "organizational_design",
    "tri_thuc": "learning_methodology",
    "quyet_dinh": "cognition",
    "ra_quyet_dinh": "cognition",
}

# Grand Domains: 5 high-level knowledge highways
GRAND_DOMAINS: dict[str, dict[str, Any]] = {
    "tech": {
        "title": "💻 Công Nghệ & Hệ Thống (Technology & Systems)",
        "keywords": [
            "ai", "artificial_intelligence", "machine_learning", "deep_learning",
            "computing", "digital", "data", "engineering", "software", "technology",
            "computer_science", "security", "bim", "system",
        ],
    },
    "cognition": {
        "title": "🧠 Nhận Thức & Phát Triển (Cognition & Growth)",
        "keywords": [
            "cognition", "cognitive", "learning", "neuroscience", "psychology", "philosophy",
            "phat_trien", "personal", "education", "epistemology", "decision_making",
            "mental_model", "thinking",
        ],
    },
    "business": {
        "title": "💰 Kinh Doanh & Tài Chính (Business & Economics)",
        "keywords": [
            "business", "economics", "entrepreneurship", "finance", "sales",
            "marketing", "pricing", "commerce",
        ],
    },
    "management": {
        "title": "👥 Quản Trị & Chiến Lược (Management & Strategy)",
        "keywords": [
            "management", "culture", "hr", "human_resources", "innovation",
            "leadership", "organization", "organizational_behavior",
            "organizational_design", "strategy", "productivity", "knowledge_management",
        ],
    },
    "society_science": {
        "title": "🌐 Xã Hội, Pháp Luật & Khoa Học (Society, Law & Science)",
        "keywords": [
            "society", "sociology", "law", "legal", "game_theory", "policy", "science",
        ],
    },
}


def normalize_domain_tag(raw_tag: str) -> str:
    """Normalize a domain tag by stripping Vietnamese diacritics and symbols.

    Args:
        raw_tag: Raw tag string (e.g. 'phát-triển/cá_nhân' or 'ai').

    Returns:
        Clean ASCII snake_cased string.
    """
    if not isinstance(raw_tag, str):
        raw_tag = str(raw_tag or "")
    s = raw_tag.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("-", "_").replace("/", "_").lower().strip()


@functools.lru_cache(maxsize=2048)
def _resolve_single_tag(tag: str) -> frozenset[str]:
    """Resolve a single tag string to matching Grand Domain categories."""
    raw = tag[7:] if tag.startswith("domain/") else tag
    norm = normalize_domain_tag(raw)
    alias = DOMAIN_ALIASES.get(norm, norm)
    padded = f"_{alias}_"
    gds = set()
    for cat, info in GRAND_DOMAINS.items():
        if alias == cat or any(f"_{kw}_" in padded or alias == kw for kw in info["keywords"]):
            gds.add(cat)
    return frozenset(gds)


def resolve_grand_domains(tags: list[str] | str | None) -> set[str]:
    """Resolve a list of tags to a set of Grand Domain categories via padded token matching.

    Args:
        tags: List of tag strings from frontmatter (e.g. ['domain/software_engineering']) or single string.

    Returns:
        Set of matching Grand Domain identifiers (e.g. {'tech'}).
    """
    if isinstance(tags, str):
        tags = [tags]
    gds: set[str] = set()
    for tag in tags or []:
        if isinstance(tag, str) and tag.strip():
            gds.update(_resolve_single_tag(tag.strip()))
    return gds


__all__ = [
    "DOMAIN_ALIASES",
    "GRAND_DOMAINS",
    "normalize_domain_tag",
    "resolve_grand_domains",
]
