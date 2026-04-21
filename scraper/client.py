import time
import logging
from typing import Optional
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from datetime import datetime

from .config import settings
from .search_strategy import get_strategy_urls
from .exceptions import ClientException

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Prevents cascading failures when remote service is down"""

    def __init__(self, failure_threshold: int = 5, timeout_seconds: int = 300):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.last_failure_time = None
        self.timeout_seconds = timeout_seconds
        self.state = "closed"

    def record_failure(self) -> None:
        """Record a failure"""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.error(
                "circuit_breaker_opened",
                extra={"extra_data": {"failure_count": self.failure_count}}
            )

    def is_open(self) -> bool:
        """Check if circuit breaker is open"""
        if self.state == "open":
            elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
            if elapsed > self.timeout_seconds:
                self.state = "half-open"
                self.failure_count = 0
                return False
            return True
        return False

    def record_success(self) -> None:
        """Record successful operation"""
        self.failure_count = 0
        self.state = "closed"


class GetOnBoardClient:
    """Web client for GetonBoard with resilience and observability"""

    def __init__(self, driver: Optional[webdriver.Chrome] = None):
        self.driver = driver
        self.circuit_breaker = CircuitBreaker()
        if not self.driver:
            self._init_driver()
        logger.info("GetOnBoardClient initialized")

    def _init_driver(self) -> None:
        """Initialize or restart Chrome driver"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.warning(f"Error quitting driver: {e}")

        try:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument(f"user-agent={settings.user_agent}")

            # Try manual path first, fallback to webdriver-manager
            chromedriver_path = None
            manual_paths = [
                str(Path.home() / ".wdm/drivers/chromedriver/mac64/147.0.7727.57/chromedriver-mac-arm64/chromedriver"),
                "/usr/local/bin/chromedriver",
                "/opt/homebrew/bin/chromedriver",
            ]

            for path in manual_paths:
                if Path(path).exists():
                    chromedriver_path = path
                    logger.debug(f"Found chromedriver at {path}")
                    break

            if not chromedriver_path:
                logger.debug("Using webdriver-manager to locate chromedriver")
                raw_path = ChromeDriverManager().install()
                # webdriver-manager sometimes returns a non-executable file
                # (e.g. THIRD_PARTY_NOTICES.chromedriver) instead of the
                # actual binary. Resolve to the real executable in the same dir.
                resolved = Path(raw_path).parent / "chromedriver"
                chromedriver_path = str(resolved) if resolved.exists() else raw_path

            self.driver = webdriver.Chrome(
                service=Service(chromedriver_path),
                options=options,
            )
            logger.debug("Chrome driver initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Chrome driver: {e}", exc_info=True)
            raise ClientException("Cannot initialize Chrome driver", original_error=e)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type(ClientException),
        before_sleep=before_sleep_log(logger, logging.INFO),
    )
    def search(self, search_term: str) -> str:
        """Search for jobs by navigating to category URLs"""
        if self.circuit_breaker.is_open():
            raise ClientException("Circuit breaker is open - backing off")

        try:
            strategy_urls = get_strategy_urls(search_term)
            logger.info(
                "search_started",
                extra={"extra_data": {"search_term": search_term}}
            )

            for strategy_url in strategy_urls:
                try:
                    self.driver.get(strategy_url)
                    time.sleep(4)

                    WebDriverWait(self.driver, 10).until(
                        lambda d: len(
                            d.find_elements(By.CLASS_NAME, "gb-results-list__item")
                        ) > 0
                    )

                    html = self.driver.page_source
                    self.circuit_breaker.record_success()
                    logger.info("search_completed", extra={"extra_data": {"search_term": search_term}})
                    return html

                except Exception as e:
                    logger.warning(f"Strategy URL failed: {strategy_url}")
                    continue

            html = self.driver.page_source
            self.circuit_breaker.record_success()
            return html

        except Exception as e:
            self.circuit_breaker.record_failure()
            raise ClientException(f"Failed to search for '{search_term}'", original_error=e)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ClientException),
    )
    def get_job_details(self, url: str) -> str:
        """Fetch job details from a specific job posting URL"""
        try:
            logger.debug(f"Fetching job details from: {url}")
            self.driver.get(url)

            try:
                WebDriverWait(self.driver, settings.timeout).until(
                    lambda d: len(d.find_elements(By.TAG_NAME, "p")) > 0
                )
            except Exception:
                time.sleep(3)

            html = self.driver.page_source
            self.circuit_breaker.record_success()
            return html

        except Exception as e:
            if "invalid session id" in str(e).lower():
                logger.warning(f"Invalid session - reinitializing driver")
                self._init_driver()
                try:
                    self.driver.get(url)
                    time.sleep(3)
                    return self.driver.page_source
                except Exception as retry_error:
                    self.circuit_breaker.record_failure()
                    raise ClientException(f"Failed to fetch details", url=url, original_error=retry_error)
            else:
                self.circuit_breaker.record_failure()
                raise ClientException(f"Failed to fetch job details", url=url, original_error=e)

    def close(self) -> None:
        """Close the WebDriver gracefully"""
        try:
            if self.driver:
                self.driver.quit()
                logger.debug("WebDriver closed successfully")
        except Exception as e:
            logger.warning(f"Error closing WebDriver: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
