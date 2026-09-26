"""VvC Second Brain — Wiki Health: Title Standardizer & Orthographic Healer.

Corrects regional homophone typos in concept stems/titles, executes single-pass
vault-wide batch wikilink updates upon renaming, and standardizes raw/non-academic
titles to scholarly Vietnamese Title Case.
Part of Deep Module package services.wiki_health.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

from core.config import cfg
from core.frontmatter import build_frontmatter, extract_body, normalize_stem, parse_frontmatter
from core.llm import call_llm
from core.log import log
from .linter import VaultLinter

_logger = logging.getLogger("vvc.health.title")


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


def _detect_orthographic_typo(title: str, summary: str) -> str | None:
    """Query LLM to detect homophone/orthographic typos."""
    prompt = (
        f"Khái niệm sau đây có bị lỗi chính tả nghiêm trọng do nhầm lẫn đồng âm vùng miền (ví dụ: Tr/Ch, S/X, D/Gi/R) không?\n"
        f"Title: {title}\nSummary: {summary}\n\n"
        f"Trả về ĐÚNG 1 JSON object (KHÔNG giải thích thêm):\n"
        f"{{\"is_typo\": true/false, \"correct\": \"Tên Đúng (nếu có)\"}}\n"
    )
    result = call_llm(prompt, task="correction")
    if not result:
        return None
    try:
        match = re.search(r"\{.*?\}", result, re.DOTALL)
        if match:
            ans = json.loads(match.group(0))
            if ans.get("is_typo") and ans.get("correct"):
                correct = ans["correct"].strip()
                if correct.lower() != title.lower() and len(correct) > 2:
                    return correct
    except Exception as e:
        _logger.warning(f"OrthographicHealer failed parsing JSON: {e}")
    return None


class OrthographicHealer:
    """Checks and heals orthographic/homophone errors in concept titles."""

    def __init__(self, concepts: list[dict] | None = None):
        if concepts is not None:
            self.concepts = concepts
        else:
            self.concepts = VaultLinter().concepts

    def heal(self, batch_size: int = 20) -> int:
        sorted_concepts = sorted(
            self.concepts,
            key=lambda c: str(c.get("date_modified", "")),
            reverse=True,
        )
        renames = {}
        for c in sorted_concepts[:batch_size]:
            title = c.get("title", c["_stem"])
            correct = _detect_orthographic_typo(title, c.get("summary", ""))
            if correct:
                old_stem = c["_stem"]
                new_stem = normalize_stem(correct)
                if old_stem != new_stem:
                    renames[old_stem] = (new_stem, correct, c)

        successful_renames = {}
        healed_count = 0
        for old_stem, (new_stem, correct_title, c) in renames.items():
            if self._apply_rename_only(c, correct_title, old_stem, new_stem):
                successful_renames[old_stem] = new_stem
                healed_count += 1

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


def _is_non_standard_concept(c: dict) -> bool:
    """Check if concept title violates naming standards."""
    title = c.get("title", "")
    stem = c.get("_stem", "")
    return not title or "_" in title or stem != normalize_stem(title)


def _query_standardized_title(title: str, stem: str, summary: str) -> str | None:
    """Query LLM to produce academic Title Case Vietnamese title."""
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
        return None
    correct = result.strip().strip('"').strip("'")
    return correct if correct.lower() != title.lower() and len(correct) > 2 else None


class TitleStandardizer:
    """Detects and standardizes raw, non-academic, or incorrectly formatted concept titles."""

    def __init__(self, concepts: list[dict] | None = None):
        if concepts is not None:
            self.concepts = concepts
        else:
            self.concepts = VaultLinter().concepts

    def standardize(self, batch_size: int = 15) -> int:
        non_standard = [c for c in self.concepts if _is_non_standard_concept(c)]
        if not non_standard:
            return 0

        sorted_non_standard = sorted(
            non_standard,
            key=lambda x: str(x.get("date_modified", "")),
            reverse=True,
        )
        healed_count = 0
        renames = {}

        for c in sorted_non_standard[:batch_size]:
            title = c.get("title", c["_stem"])
            stem = c["_stem"]
            correct = _query_standardized_title(title, stem, c.get("summary", ""))
            if not correct:
                continue

            new_stem = normalize_stem(correct)
            if stem != new_stem:
                if self._apply_rename_only(c, correct, stem, new_stem):
                    renames[stem] = new_stem
                    healed_count += 1
            elif self._apply_frontmatter_update_only(c, correct):
                healed_count += 1

        if renames:
            _update_all_links_vault_wide_batch(renames)

        if healed_count:
            log("heal", f"TitleStandardizer standardized {healed_count} concept titles")
        return healed_count

    def _apply_rename_only(self, c: dict, correct_title: str, old_stem: str, new_stem: str) -> bool:
        """Rename physical file and update title/date_modified in frontmatter."""
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


__all__ = [
    "OrthographicHealer",
    "TitleStandardizer",
    "heal_orthography",
    "standardize_titles",
    "_update_all_links_vault_wide_batch",
]
