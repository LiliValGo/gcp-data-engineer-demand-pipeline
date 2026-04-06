"""
Tests for scraper/checkpoint.py (DuckDB backend)

What we test:
- Basic read/write operations (mark_processed, is_processed)
- Upsert semantics via ON CONFLICT
- Failed URL tracking (mark_failed)
- Aggregate statistics (get_stats)
- Reset functionality
- Context manager protocol

All tests use tmp_path (pytest built-in fixture) to create isolated
DuckDB files — no shared state between tests.
"""

import pytest
from pathlib import Path

from scraper.checkpoint import ScrapingCheckpoint
from scraper.exceptions import CheckpointException


@pytest.fixture
def checkpoint(tmp_path) -> ScrapingCheckpoint:
    """
    Fresh ScrapingCheckpoint backed by a temporary DuckDB file.

    tmp_path is a pytest built-in fixture that provides a unique
    temporary directory for each test. No manual cleanup needed.
    """
    db_path = tmp_path / "test_checkpoint.db"
    cp = ScrapingCheckpoint(db_path=str(db_path))
    yield cp
    cp.close()


class TestIsProcessed:

    def test_returns_false_for_untracked_url(self, checkpoint):
        assert checkpoint.is_processed("https://example.com/job/1") is False

    def test_returns_true_after_mark_processed(self, checkpoint):
        url = "https://example.com/job/1"
        checkpoint.mark_processed(url=url, search_term="data engineer", role="data_engineer")
        assert checkpoint.is_processed(url) is True

    def test_failed_url_is_not_considered_processed(self, checkpoint):
        url = "https://example.com/job/2"
        checkpoint.mark_failed(url=url, search_term="data engineer", role="data_engineer", error_message="timeout")
        # is_processed only returns True for status='success'
        assert checkpoint.is_processed(url) is False


class TestMarkProcessed:

    def test_stores_all_fields(self, checkpoint):
        url = "https://example.com/job/3"
        checkpoint.mark_processed(
            url=url,
            search_term="ml engineer",
            role="data_engineer",
            extraction_method="class_search",
            confidence_score=0.87,
            metadata={"scraper_version": "2.0"},
        )
        result = checkpoint.conn.execute(
            "SELECT * FROM processed_urls WHERE url = ?", (url,)
        ).fetchone()

        assert result is not None
        assert result[1] == "ml engineer"   # search_term
        assert result[7] == "success"        # status
        assert result[5] == pytest.approx(0.87, abs=0.001)  # confidence_score

    def test_upsert_overwrites_previous_record(self, checkpoint):
        """
        Marking the same URL twice should update the record, not create a duplicate.
        This validates the ON CONFLICT ... DO UPDATE SET behaviour.
        """
        url = "https://example.com/job/4"
        checkpoint.mark_processed(url=url, search_term="data engineer", role="data_engineer", confidence_score=0.5)
        checkpoint.mark_processed(url=url, search_term="data engineer", role="data_engineer", confidence_score=0.9)

        rows = checkpoint.conn.execute(
            "SELECT COUNT(*) FROM processed_urls WHERE url = ?", (url,)
        ).fetchone()[0]
        assert rows == 1  # still one row

        score = checkpoint.conn.execute(
            "SELECT confidence_score FROM processed_urls WHERE url = ?", (url,)
        ).fetchone()[0]
        assert score == pytest.approx(0.9, abs=0.001)  # updated to latest


class TestMarkFailed:

    def test_stores_failed_status(self, checkpoint):
        url = "https://example.com/job/5"
        checkpoint.mark_failed(url=url, search_term="data engineer", role="data_engineer", error_message="connection refused")

        status = checkpoint.conn.execute(
            "SELECT status FROM processed_urls WHERE url = ?", (url,)
        ).fetchone()[0]
        assert status == "failed"

    def test_error_message_stored_in_metadata(self, checkpoint):
        url = "https://example.com/job/6"
        checkpoint.mark_failed(url=url, search_term="data engineer", role="data_engineer", error_message="page not found")

        import json
        metadata_raw = checkpoint.conn.execute(
            "SELECT metadata FROM processed_urls WHERE url = ?", (url,)
        ).fetchone()[0]
        metadata = json.loads(metadata_raw)
        assert metadata["error"] == "page not found"


class TestGetStats:

    def test_empty_checkpoint_returns_zeros(self, checkpoint):
        stats = checkpoint.get_stats()
        assert stats["total_processed"] == 0
        assert stats["successful"] == 0
        assert stats["failed"] == 0
        assert stats["avg_confidence"] == 0.0

    def test_counts_success_and_failed_correctly(self, checkpoint):
        checkpoint.mark_processed("https://a.com/1", "de", "data_engineer", confidence_score=0.8)
        checkpoint.mark_processed("https://a.com/2", "de", "data_engineer", confidence_score=0.6)
        checkpoint.mark_failed("https://a.com/3", "de", "data_engineer", "error")

        stats = checkpoint.get_stats()
        assert stats["total_processed"] == 3
        assert stats["successful"] == 2
        assert stats["failed"] == 1

    def test_avg_confidence_calculated_correctly(self, checkpoint):
        checkpoint.mark_processed("https://b.com/1", "de", "data_engineer", confidence_score=0.8)
        checkpoint.mark_processed("https://b.com/2", "de", "data_engineer", confidence_score=0.6)

        stats = checkpoint.get_stats()
        assert stats["avg_confidence"] == pytest.approx(0.7, abs=0.001)

    def test_role_filter_isolates_results(self, checkpoint):
        checkpoint.mark_processed("https://c.com/1", "de", "data_engineer")
        checkpoint.mark_processed("https://c.com/2", "fe", "frontend_engineer")

        stats_de = checkpoint.get_stats(role="data_engineer")
        assert stats_de["total_processed"] == 1

        stats_all = checkpoint.get_stats()
        assert stats_all["total_processed"] == 2


class TestReset:

    def test_reset_all_clears_all_records(self, checkpoint):
        checkpoint.mark_processed("https://d.com/1", "de", "data_engineer")
        checkpoint.mark_processed("https://d.com/2", "de", "data_engineer")
        checkpoint.reset()

        count = checkpoint.conn.execute("SELECT COUNT(*) FROM processed_urls").fetchone()[0]
        assert count == 0

    def test_reset_by_role_only_removes_matching(self, checkpoint):
        checkpoint.mark_processed("https://e.com/1", "de", "data_engineer")
        checkpoint.mark_processed("https://e.com/2", "fe", "frontend_engineer")
        checkpoint.reset(role="data_engineer")

        remaining = checkpoint.conn.execute(
            "SELECT role FROM processed_urls"
        ).fetchall()
        assert len(remaining) == 1
        assert remaining[0][0] == "frontend_engineer"


class TestContextManager:

    def test_context_manager_closes_connection(self, tmp_path):
        db_path = tmp_path / "ctx_test.db"
        with ScrapingCheckpoint(db_path=str(db_path)) as cp:
            cp.mark_processed("https://ctx.com/1", "de", "data_engineer")
            assert cp.conn is not None
        # After __exit__, conn.close() was called
        # Attempting a query should raise an error
        with pytest.raises(Exception):
            cp.conn.execute("SELECT 1")


class TestGetUnprocessedUrls:

    def test_filters_out_processed_urls(self, checkpoint):
        checkpoint.mark_processed("https://f.com/processed", "de", "data_engineer")
        unprocessed = checkpoint.get_unprocessed_urls([
            "https://f.com/processed",
            "https://f.com/new",
        ])
        assert unprocessed == ["https://f.com/new"]

    def test_returns_all_when_none_processed(self, checkpoint):
        urls = ["https://g.com/1", "https://g.com/2"]
        result = checkpoint.get_unprocessed_urls(urls)
        assert result == urls
