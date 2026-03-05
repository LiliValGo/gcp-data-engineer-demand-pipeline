"""Checkpoint system for idempotent scraping operations"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
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
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.row_factory = sqlite3.Row
            logger.info(
                f"Connected to checkpoint database: {self.db_path}"
            )
        except sqlite3.Error as e:
            logger.error(f"Failed to connect to checkpoint DB: {e}")
            raise CheckpointException(
                f"Cannot initialize checkpoint database: {str(e)}"
            )

    def _init_tables(self) -> None:
        """Create tables if they don't exist"""
        try:
            cursor = self.conn.cursor()

            # Main table for processed URLs
            cursor.execute(
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
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_role_search_term
                ON processed_urls(role, search_term)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_processed_at
                ON processed_urls(processed_at)
                """
            )

            self.conn.commit()
            logger.debug("Checkpoint tables initialized")

        except sqlite3.Error as e:
            logger.error(f"Failed to initialize checkpoint tables: {e}")
            raise CheckpointException(f"Cannot create checkpoint tables: {str(e)}")

    def is_processed(self, url: str) -> bool:
        """Check if URL has been processed"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT 1 FROM processed_urls WHERE url = ? AND status = 'success'",
                (url,),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
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
            cursor = self.conn.cursor()
            metadata_json = json.dumps(metadata) if metadata else None

            cursor.execute(
                """
                INSERT OR REPLACE INTO processed_urls
                (url, search_term, role, processed_at, extraction_method,
                 confidence_score, metadata, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    search_term,
                    role,
                    datetime.utcnow().isoformat(),
                    extraction_method,
                    confidence_score,
                    metadata_json,
                    status,
                ),
            )
            self.conn.commit()
            logger.debug(f"Marked URL as processed: {url}")

        except sqlite3.Error as e:
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
            cursor = self.conn.cursor()

            if role:
                cursor.execute(
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
                )
            else:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                        AVG(confidence_score) as avg_confidence
                    FROM processed_urls
                    """
                )

            row = cursor.fetchone()
            return {
                "total_processed": row["total"] or 0,
                "successful": row["success"] or 0,
                "failed": row["failed"] or 0,
                "avg_confidence": row["avg_confidence"] or 0.0,
            }

        except sqlite3.Error as e:
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
            cursor = self.conn.cursor()

            if role:
                cursor.execute(
                    "DELETE FROM processed_urls WHERE role = ?",
                    (role,),
                )
                logger.warning(f"Reset checkpoints for role: {role}")
            else:
                cursor.execute("DELETE FROM processed_urls")
                logger.warning("Reset all checkpoints")

            self.conn.commit()

        except sqlite3.Error as e:
            logger.error(f"Error resetting checkpoints: {e}")
            raise CheckpointException(f"Cannot reset checkpoints: {str(e)}")

    def close(self) -> None:
        """Close database connection"""
        try:
            if self.conn:
                self.conn.close()
                logger.debug("Checkpoint database closed")
        except sqlite3.Error as e:
            logger.error(f"Error closing checkpoint database: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
