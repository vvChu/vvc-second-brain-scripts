"""VvC Second Brain — Unit Tests for Artifact Engine / Worker Dispatcher (v1.0).

Tests placeholder detection, strategy dispatching, error isolation,
and custom adapter registration in scripts/services/worker_dispatcher.py.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from services.worker_dispatcher import (
    _init_default_registry,
    register_artifact_adapter,
    trigger_workers,
)


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure registry is reset to defaults before and after each test."""
    _init_default_registry()
    yield
    _init_default_registry()


def test_trigger_workers_empty_response():
    """Should return empty list for empty response."""
    assert trigger_workers("") == []
    assert trigger_workers(None) == []  # type: ignore[arg-type]


def test_trigger_workers_no_placeholders():
    """Should return empty list when no recognized placeholders are in text."""
    sample = "This is a normal explanation without any embedded diagram wiki-links."
    assert trigger_workers(sample) == []


@patch("services.worker_dispatcher.trigger_mermaid_generation")
def test_trigger_workers_mermaid(mock_mermaid):
    """Should detect mermaid diagrams with and without display dimensions."""
    sample = (
        "Here is the architecture overview:\n\n"
        "![[system_flow.mermaid.md]]\n\n"
        "And the second diagram:\n"
        "![[data_pipeline.mermaid.md|100%]]\n"
    )
    result = trigger_workers(sample, query="draw architecture")

    assert result == ["system_flow.mermaid.md", "data_pipeline.mermaid.md"]
    assert mock_mermaid.call_count == 2
    mock_mermaid.assert_any_call("system_flow.mermaid.md", sample)
    mock_mermaid.assert_any_call("data_pipeline.mermaid.md", sample)


@patch("services.worker_dispatcher.trigger_excalidraw_generation")
def test_trigger_workers_excalidraw(mock_excali):
    """Should detect excalidraw placeholders and invoke excalidraw worker."""
    sample = "Visual diagram: ![[infra_layout.excalidraw.md|800]]"
    result = trigger_workers(sample)

    assert result == ["infra_layout.excalidraw.md"]
    mock_excali.assert_called_once_with("infra_layout.excalidraw.md", sample)


@patch("services.worker_dispatcher.trigger_qc_generation")
def test_trigger_workers_qc_query_forwarding(mock_qc):
    """Should forward user query to QC matrix worker."""
    sample = "Audit results:\n![[audit_matrix.csv]]\n![[report_summary.xlsx]]"
    result = trigger_workers(sample, query="audit column QA")

    assert result == ["audit_matrix.csv", "report_summary.xlsx"]
    assert mock_qc.call_count == 2
    mock_qc.assert_any_call("audit_matrix.csv", sample, "audit column QA")
    mock_qc.assert_any_call("report_summary.xlsx", sample, "audit column QA")


@patch("services.worker_dispatcher.trigger_d2_generation")
def test_trigger_workers_d2(mock_d2):
    """Should detect .d2.svg placeholders with and without pipes and dispatch to d2 worker."""
    sample = (
        "System architecture:\n\n"
        "![[system_arch.d2.svg]]\n\n"
        "Detailed pipeline:\n"
        "![[pipeline.d2.svg|100%]]\n"
    )
    result = trigger_workers(sample)

    assert result == ["system_arch.d2.svg", "pipeline.d2.svg"]
    assert mock_d2.call_count == 2
    mock_d2.assert_any_call("system_arch.d2.svg", sample)
    mock_d2.assert_any_call("pipeline.d2.svg", sample)


@patch("services.worker_dispatcher.trigger_mermaid_generation")
@patch("services.worker_dispatcher.trigger_doc_generation")
def test_trigger_workers_multiple_types(mock_doc, mock_mermaid):
    """Should dispatch multiple different artifact types in a single response."""
    sample = (
        "Project deliverables:\n"
        "- Diagram: ![[flowchart.mermaid.md]]\n"
        "- Document: ![[spec.docx]]\n"
    )
    result = trigger_workers(sample)

    assert "flowchart.mermaid.md" in result
    assert "spec.docx" in result
    mock_mermaid.assert_called_once_with("flowchart.mermaid.md", sample)
    mock_doc.assert_called_once_with("spec.docx", sample)


def test_trigger_workers_error_isolation():
    """Faulty adapter should not crash dispatcher or prevent other adapters from executing."""
    bad_handler = MagicMock(side_effect=RuntimeError("Worker crashed!"))
    good_handler = MagicMock()

    register_artifact_adapter(r"!\[\[([^\]|]+\.bad)\]\]", bad_handler, name="bad_worker")
    register_artifact_adapter(r"!\[\[([^\]|]+\.good)\]\]", good_handler, name="good_worker")

    sample = "Items: ![[fail.bad]] and ![[pass.good]]"
    result = trigger_workers(sample)

    # Bad worker was called but its error was caught and logged
    bad_handler.assert_called_once_with("fail.bad", sample, "")
    # Good worker still successfully executed
    good_handler.assert_called_once_with("pass.good", sample, "")
    # Only the successful artifact is in the returned list
    assert result == ["pass.good"]


def test_register_custom_artifact_adapter():
    """Should allow dynamic registration of custom artifact handlers (Open-Closed)."""
    custom_handler = MagicMock()
    register_artifact_adapter(
        r"!\[\[([^\]|]+\.svg)(?:\|[^\]]*)?\]\]",
        custom_handler,
        name="svg_renderer",
    )

    sample = "Vector graphic: ![[vector_diagram.svg|500]]"
    result = trigger_workers(sample, query="render svg")

    assert result == ["vector_diagram.svg"]
    custom_handler.assert_called_once_with("vector_diagram.svg", sample, "render svg")


@patch("services.worker_dispatcher.trigger_excalidraw_generation")
@patch("services.worker_dispatcher.trigger_mermaid_generation")
@patch("services.worker_dispatcher.trigger_d2_generation")
def test_trigger_workers_malformed_snake_case_extensions(mock_d2, mock_mermaid, mock_excali):
    """Should automatically normalize snake_cased extensions like _excalidraw_md into .excalidraw.md."""
    sample = (
        "Here is an excalidraw: ![[mo_hinh_to_chuc_ai_agent_excalidraw_md|100%]]\n"
        "And a mermaid: ![[system_flow_mermaid_md]]\n"
        "And a d2: ![[arch_diagram_d2_svg|100%]]\n"
    )
    result = trigger_workers(sample)

    assert result == [
        "mo_hinh_to_chuc_ai_agent.excalidraw.md",
        "system_flow.mermaid.md",
        "arch_diagram.d2.svg",
    ]
    mock_excali.assert_called_once_with("mo_hinh_to_chuc_ai_agent.excalidraw.md", sample)
    mock_mermaid.assert_called_once_with("system_flow.mermaid.md", sample)
    mock_d2.assert_called_once_with("arch_diagram.d2.svg", sample)

