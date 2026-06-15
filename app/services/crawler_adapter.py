from typing import Callable

from scripts import football_all_modules_once_scraper as scraper


class CrawlerAdapter:
    def __init__(self, headless: bool = True):
        self.headless = headless

    def crawl_all_modules(
        self,
        progress_callback: Callable[[str], None] | None = None,
        refresh_mode: str = "full",
    ) -> dict:
        return scraper.crawl_payload(
            selected_modules=None,
            limit_per_module=None,
            progress_callback=progress_callback,
            headless=self.headless,
            refresh_mode=refresh_mode,
        )

    def crawl_modules(
        self,
        module_codes: list[str],
        progress_callback: Callable[[str], None] | None = None,
        refresh_mode: str = "full",
    ) -> dict:
        return scraper.crawl_payload(
            selected_modules=module_codes,
            limit_per_module=None,
            progress_callback=progress_callback,
            headless=self.headless,
            refresh_mode=refresh_mode,
        )
