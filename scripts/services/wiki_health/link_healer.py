"""VvC Second Brain — Wiki Health: Link Healer.

Auto-creates quality stubs for broken wiki-links with LLM semantic arbitration,
heuristic pre-filtering, Whitelist bypass, rate limiting, and unlinking rejected targets.
Part of Deep Module package services.wiki_health.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path

from core.config import cfg
from core.frontmatter import build_concept_frontmatter, normalize_stem
from core.llm import call_llm
from core.log import log
from .linter import LintReport, lint_vault
from .stub_lifecycle import manage_stub_lifecycle

_logger = logging.getLogger("vvc.health.healer")

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


class LinkHealer:
    """Auto-creates quality stubs for broken wiki-links (Facade pattern)."""

    def __init__(self):
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
            config_path = cfg.vault_root / "scripts" / "config.yaml"
            if not config_path.exists():
                config_path = Path(__file__).resolve().parents[2] / "config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    raw_cfg = yaml.safe_load(f)
                    health_cfg = raw_cfg.get("health", {})
                    wl = health_cfg.get("whitelist_stubs", [])
                    if isinstance(wl, list):
                        self.whitelisted_stubs = {normalize_stem(item) for item in wl if isinstance(item, str)}
        except Exception as e:
            _logger.warning(f"Failed to load whitelist_stubs from config.yaml: {e}")

    def _check_stub_approval(self, target: str) -> bool | None:
        """Check if target is approved as a valid concept stub."""
        norm_target = normalize_stem(target)
        if norm_target in getattr(self, "whitelisted_stubs", set()):
            _logger.info(f"Whitelisted stub approved directly: {target}")
            return True
        time.sleep(3.0)
        return self._is_valid_concept(target)

    def _handle_rejected_target(self, target: str, sources: list[str]) -> None:
        """Cache rejected target and unlink it from source notes."""
        _logger.debug(f"Rejected by LLM: {target}")
        self.rejected_cache.add(target)
        try:
            self.rejected_file.write_text(json.dumps(list(self.rejected_cache)), encoding="utf-8")
        except OSError:
            pass
        self._unlink_in_sources(target, sources)

    def _handle_approved_target(self, target: str, sources: list[str]) -> bool:
        """Clean rejected cache if needed and create stub note."""
        if target in self.rejected_cache:
            self.rejected_cache.discard(target)
            _logger.info(f"Self-healed cache: removed whitelisted stub '{target}' from rejected stubs list.")
            try:
                self.rejected_file.write_text(json.dumps(list(self.rejected_cache)), encoding="utf-8")
            except OSError:
                pass
        return bool(self._create_stub(target, sources))

    def heal(self, report: LintReport, max_heal_limit: int = 15) -> int:
        broken = report.get("broken_links", [])
        if not broken:
            return 0

        targets: dict[str, list[str]] = defaultdict(list)
        for entry in broken:
            targets[entry["to"]].append(entry["from"])
        sorted_targets = sorted(targets.items(), key=lambda item: len(item[1]), reverse=True)
        if len(sorted_targets) > max_heal_limit:
            _logger.info(f"LinkHealer: Found {len(sorted_targets)} broken links. Limiting to top {max_heal_limit} most frequent targets to protect API.")
            sorted_targets = sorted_targets[:max_heal_limit]

        created = consecutive_errors = 0
        for target, sources in sorted_targets:
            if self._heuristic_reject(target):
                self._unlink_in_sources(target, sources)
                continue

            is_valid = self._check_stub_approval(target)
            if is_valid is None:
                consecutive_errors += 1
                _logger.debug(f"LLM API failure for: {target} ({consecutive_errors}/3). Backing off 30s...")
                time.sleep(30)
                if consecutive_errors >= 3:
                    _logger.error("Consecutive API failures reached 3. Aborting LinkHealer to protect API.")
                    break
                continue

            consecutive_errors = 0
            if not is_valid:
                self._handle_rejected_target(target, sources)
            elif self._handle_approved_target(target, sources):
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
        """Scan all stubs, purge orphan stubs and record stale pending stubs (delegates to stub_lifecycle)."""
        return manage_stub_lifecycle()

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


__all__ = [
    "_REJECT_PATTERNS",
    "LinkHealer",
    "heal_broken_links",
]
