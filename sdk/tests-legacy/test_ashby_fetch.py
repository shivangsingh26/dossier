"""Tests for fetch_jobs_ashby() in watchlist_agent.py.

NOTE: Field names (title, locationName, publishedDate, jobPostingUrl, descriptionHtml)
are based on standard Ashby API documentation. Verify live before adding real companies
to profile/target_companies.json (see Task 7 in the plan).
"""
import pytest
from unittest.mock import patch, MagicMock
from dossier_sdk.agents.watchlist_agent import fetch_jobs_ashby

# Matches the Ashby public API schema documented in the project plan.
# Three postings: one valid ML/India job, one non-ML (HR), one non-India (US).
MOCK_ASHBY_RESPONSE = {
    "results": [
        {
            "title": "Machine Learning Engineer",
            "locationName": "Bengaluru, India",
            "publishedDate": "2026-05-01T00:00:00.000Z",
            "jobPostingUrl": "https://jobs.ashbyhq.com/phonepe/abc123",
            "descriptionHtml": "<p>We are looking for an MLE to build recommendation systems.</p>",
        },
        {
            # NOT ML — title filter should drop this
            "title": "HR Business Partner",
            "locationName": "Mumbai",
            "publishedDate": "2026-05-01T00:00:00.000Z",
            "jobPostingUrl": "https://jobs.ashbyhq.com/phonepe/def456",
            "descriptionHtml": "<p>HR role managing talent acquisition.</p>",
        },
        {
            # NOT India — location filter should drop this
            "title": "Data Scientist",
            "locationName": "San Francisco, USA",
            "publishedDate": "2026-05-01T00:00:00.000Z",
            "jobPostingUrl": "https://jobs.ashbyhq.com/phonepe/ghi789",
            "descriptionHtml": "<p>Data scientist role at PhonePe US office.</p>",
        },
    ]
}


def make_mock_response(data: dict) -> MagicMock:
    """Build a mock requests.Response that returns the given data as JSON."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = data
    return mock


def test_ashby_filters_non_ml_titles():
    with patch("requests.get", return_value=make_mock_response(MOCK_ASHBY_RESPONSE)):
        jobs = fetch_jobs_ashby("PhonePe", "phonepe")
    titles = [j["title"] for j in jobs]
    assert "Machine Learning Engineer" in titles
    assert "HR Business Partner" not in titles


def test_ashby_filters_non_india_locations():
    with patch("requests.get", return_value=make_mock_response(MOCK_ASHBY_RESPONSE)):
        jobs = fetch_jobs_ashby("PhonePe", "phonepe")
    locations = [j["location"] for j in jobs]
    assert not any("San Francisco" in loc for loc in locations)


def test_ashby_output_shape_matches_greenhouse():
    with patch("requests.get", return_value=make_mock_response(MOCK_ASHBY_RESPONSE)):
        jobs = fetch_jobs_ashby("PhonePe", "phonepe")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["site"] == "ashby"
    assert job["company"] == "PhonePe"
    assert "title" in job
    assert "location" in job
    assert "job_url" in job
    assert "date_posted" in job
    assert "description" in job


def test_ashby_returns_empty_on_http_error():
    mock = MagicMock()
    mock.status_code = 404
    with patch("requests.get", return_value=mock):
        jobs = fetch_jobs_ashby("PhonePe", "phonepe")
    assert jobs == []


def test_ashby_returns_empty_on_network_exception():
    with patch("requests.get", side_effect=Exception("network error")):
        jobs = fetch_jobs_ashby("PhonePe", "phonepe")
    assert jobs == []
