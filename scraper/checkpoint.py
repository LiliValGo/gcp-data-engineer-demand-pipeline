"""Checkpoint system for idempotent scraping operations"""

import duckdb
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from .exceptions import CheckpointException

logger = logging.getLogger(__name__)


class ScrapingCheckpoint:
    """
    Persists processed URLs to enable idempotent scraping.

    Allows resuming scraping without reprocessing URLs already scraped.
    """

    def __init__(self, db_path: str = "data/.checkpoints/urls.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self._init_connection()
        self._init_tables()

    def _init_connection(self) -> None:
        """Initialize database connection"""
        try:
            self.conn = duckdb.connect(str(self.db_path))
            logger.info(
                f"Connected to checkpoint database: {self.db_path}"
            )
        except duckdb.Error as e:
            logger.error(f"Failed to connect to checkpoint DB: {e}")
            raise CheckpointException(
                f"Cannot initialize checkpoint database: {str(e)}"
            )

    def _init_tables(self) -> None:
        """Create tables if they don't exist"""
        try:
            # Main table for processed URLs
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_urls (
                    url TEXT PRIMARY KEY,
                    search_term TEXT,
                    role TEXT,
                    processed_at DATETIME,
                    extraction_method TEXT,
                    confidence_score REAL,
                    metadata TEXT,
                    status TEXT DEFAULT 'success'
                )
                """
            )

            # Index for faster lookups
            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_role_search_term
                ON processed_urls(role, search_term)
                """
            )

            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_processed_at
                ON processed_urls(processed_at)
                """
            )

            logger.debug("Checkpoint tables initialized")

        except duckdb.Error as e:
            logger.error(f"Failed to initialize checkpoint tables: {e}")
            raise CheckpointException(f"Cannot create checkpoint tables: {str(e)}")

    def is_processed(self, url: str) -> bool:
        """Check if URL has been processed"""
        try:
            result = self.conn.execute(
                "SELECT 1 FROM processed_urls WHERE url = ? AND status = 'success'",
                (url,),
            ).fetchone()
            return result is not None
        except duckdb.Error as e:
            logger.error(f"Error checking if URL processed: {e}")
            return False

    def mark_processed(
        self,
        url: str,
        search_term: str,
        role: str,
        extraction_method: Optional[str] = None,
        confidence_score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "success",
    ) -> None:
        """Record that a URL has been processed"""
        try:
            metadata_json = json.dumps(metadata) if metadata else None

            self.conn.execute(
                """
                INSERT INTO processed_urls
                (url, search_term, role, processed_at, extraction_method,
                 confidence_score, metadata, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (url) DO UPDATE SET
                    extraction_method = excluded.extraction_method,
                    confidence_score  = excluded.confidence_score,
                    metadata          = excluded.metadata,
                    status            = excluded.status
                """,
                (
                    url,
                    search_term,
                    role,
                    datetime.now(timezone.utc).isoformat(),
                    extraction_method,
                    confidence_score,
                    metadata_json,
                    status,
                ),
            )
            logger.debug(f"Marked URL as processed: {url}")

        except duckdb.Error as e:
            logger.error(f"Error marking URL as processed: {e}")
            raise CheckpointException(f"Cannot mark URL as processed: {str(e)}")

    def mark_failed(
        self,
        url: str,
        search_term: str,
        role: str,
        error_message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record that a URL failed processing"""
        try:
            if metadata is None:
                metadata = {}
            metadata["error"] = error_message

            self.mark_processed(
                url=url,
                search_term=search_term,
                role=role,
                metadata=metadata,
                status="failed",
            )
            logger.warning(f"Marked URL as failed: {url} - {error_message}")

        except CheckpointException:
            raise

    def get_stats(self, role: Optional[str] = None) -> Dict[str, Any]:
        """Get checkpoint statistics"""
        try:
            if role:
                row = self.conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                        AVG(confidence_score) as avg_confidence
                    FROM processed_urls
                    WHERE role = ?
                    """,
                    (role,),
                ).fetchone()
            else:
                row = self.conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                        AVG(confidence_score) as avg_confidence
                    FROM processed_urls
                    """
                ).fetchone()

            return {
                "total_processed": row[0] or 0,
                "successful": row[1] or 0,
                "failed": row[2] or 0,
                "avg_confidence": row[3] or 0.0,
            }

        except duckdb.Error as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "total_processed": 0,
                "successful": 0,
                "failed": 0,
                "avg_confidence": 0.0,
            }

    def get_unprocessed_urls(
        self,
        urls: List[str],
    ) -> List[str]:
        """Filter out URLs that have already been processed"""
        if not urls:
            return []
        try:
            placeholders = ", ".join(["?"] * len(urls))
            query = f"SELECT url FROM processed_urls WHERE status = 'success' AND url IN ({placeholders})"
            results = self.conn.execute(query, urls).fetchall()
            processed_urls = {row[0] for row in results}
            return [url for url in urls if url not in processed_urls]
        except duckdb.Error as e:
            logger.error(f"Error filtering unprocessed URLs: {e}")
            unprocessed = []
            for url in urls:
                if not self.is_processed(url):
                    unprocessed.append(url)
            return unprocessed


    def reset(self, role: Optional[str] = None) -> None:
        """
        Reset checkpoints for debugging/replay.

        Args:
            role: If specified, only reset for this role. Otherwise reset all.
        """
        try:
            if role:
                self.conn.execute(
                    "DELETE FROM processed_urls WHERE role = ?",
                    (role,),
                )
                logger.warning(f"Reset checkpoints for role: {role}")
            else:
                self.conn.execute("DELETE FROM processed_urls")
                logger.warning("Reset all checkpoints")

        except duckdb.Error as e:
            logger.error(f"Error resetting checkpoints: {e}")
            raise CheckpointException(f"Cannot reset checkpoints: {str(e)}")

    def close(self) -> None:
        """Close database connection"""
        try:
            if self.conn:
                self.conn.close()
                logger.debug("Checkpoint database closed")
        except duckdb.Error as e:
            logger.error(f"Error closing checkpoint database: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
