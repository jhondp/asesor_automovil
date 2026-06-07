import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, Page

from src.config import settings

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    source_name: str = "base"

    def __init__(self) -> None:
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    def _delay(self):
        time.sleep(settings.request_delay)

    def start_browser(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=settings.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="es-CL",
        )
        self.page = context.new_page()
        logger.info("Browser started (%s)", "headless" if settings.headless else "visible")

    def close_browser(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        logger.info("Browser closed")

    @abstractmethod
    def scrape(self):
        ...
