"""Tests orchestrator pure functions.

We mock the underlying agent modules so the tests do not call OpenAI / scrape sites.
"""
from unittest.mock import patch

import pytest

from dossier_sdk.orchestrator import RunResult, run_discovery, run_pipeline


def test_run_discovery_returns_jobs_and_result():
    fake_jobs = [{"job_id": "j1", "score": 8}, {"job_id": "j2", "score": 6}]
    with patch("dossier_sdk.orchestrator._discovery_agent_run", return_value=fake_jobs):
        result, jobs = run_discovery(hours_old=24, min_score=5)
    assert isinstance(result, RunResult)
    assert result.status == "completed"
    assert result.count == 2
    assert result.error is None
    assert jobs == fake_jobs


def test_run_discovery_catches_exception_returns_failed_result():
    with patch("dossier_sdk.orchestrator._discovery_agent_run", side_effect=RuntimeError("api down")):
        result, jobs = run_discovery(hours_old=24, min_score=5)
    assert result.status == "failed"
    assert "api down" in (result.error or "")
    assert jobs == []


def test_run_pipeline_quick_mode_runs_discovery_and_watchlist_only():
    with (
        patch("dossier_sdk.orchestrator.run_discovery") as m_disc,
        patch("dossier_sdk.orchestrator.run_watchlist") as m_watch,
        patch("dossier_sdk.orchestrator.run_company_intel") as m_intel,
        patch("dossier_sdk.orchestrator.run_gap_analysis") as m_gap,
    ):
        m_disc.return_value = (RunResult(status="completed", count=3, duration_s=1.0), [])
        m_watch.return_value = (RunResult(status="completed", count=2, duration_s=1.0), [])
        summary = run_pipeline(mode="quick", hours=24, min_score=5)
    assert "discovery" in summary["stages_run"]
    assert "watchlist" in summary["stages_run"]
    assert "company_intel" not in summary["stages_run"]
    assert "gap_analysis" not in summary["stages_run"]
    m_intel.assert_not_called()
    m_gap.assert_not_called()
