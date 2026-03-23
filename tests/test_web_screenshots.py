"""Web GUI Playwright visual tests with screenshots.

Requires: pip install playwright && playwright install chromium
"""

import json
import unittest
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from oden.web_server import create_app

# Path to sample data fixture
FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_DATA = FIXTURES_DIR / "gui_sample_data.json"

# Directory for screenshots (gitignored)
SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots"


def load_fixture() -> dict:
    """Load the GUI sample data fixture."""
    with open(SAMPLE_DATA, encoding="utf-8") as f:
        return json.load(f)


# Check if playwright is available
try:
    from playwright.async_api import async_playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright not installed — skipping visual tests")
class TestWebGUIScreenshots(AioHTTPTestCase):
    """Visual tests using Playwright to render the GUI and take screenshots."""

    async def get_application(self):
        return create_app(setup_mode=False)

    async def _setup_playwright(self):
        """Start Playwright and launch browser (async)."""
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)

    async def _teardown_playwright(self):
        """Close browser and stop Playwright (async)."""
        await self._browser.close()
        await self._pw.stop()

    def _get_base_url(self) -> str:
        """Get the base URL of the running test server."""
        return str(self.server.make_url(""))

    async def _create_page_with_mocked_data(self):
        """Create a Playwright page that intercepts API calls with fixture data."""
        fixture = load_fixture()
        page = await self._browser.new_page(viewport={"width": 1280, "height": 900})

        async def handle_route(route):
            url = route.request.url
            if "/api/logs" in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(fixture["logs"]),
                )
            elif "/api/config" in url and "/api/config-file" not in url and "/api/config/" not in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(fixture["config"]),
                )
            elif "/api/groups" in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "groups": fixture["groups"]}),
                )
            elif "/api/invitations" in url:
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "invitations": []}),
                )
            else:
                await route.continue_()

        await page.route("**/api/**", handle_route)
        return page

    async def test_dashboard_screenshot(self):
        """Take a screenshot of the main dashboard with sample data."""
        await self._setup_playwright()
        try:
            page = await self._create_page_with_mocked_data()
            await page.goto(self._get_base_url())

            # Wait for the data to load (JS polls on intervals)
            await page.wait_for_timeout(2000)

            path = SCREENSHOTS_DIR / "dashboard.png"
            await page.screenshot(path=str(path), full_page=True)
            self.assertTrue(path.exists(), "Dashboard screenshot was not created")
            self.assertGreater(path.stat().st_size, 0, "Dashboard screenshot is empty")
            await page.close()
        finally:
            await self._teardown_playwright()

    async def test_setup_page_screenshot(self):
        """Take a screenshot of the setup wizard page."""
        await self._setup_playwright()
        try:
            page = await self._browser.new_page(viewport={"width": 1280, "height": 900})
            await page.goto(self._get_base_url() + "/setup")

            await page.wait_for_timeout(1000)

            path = SCREENSHOTS_DIR / "setup.png"
            await page.screenshot(path=str(path), full_page=True)
            self.assertTrue(path.exists(), "Setup screenshot was not created")
            self.assertGreater(path.stat().st_size, 0, "Setup screenshot is empty")
            await page.close()
        finally:
            await self._teardown_playwright()

    async def test_dashboard_contains_expected_elements(self):
        """Verify the dashboard renders key UI elements."""
        await self._setup_playwright()
        try:
            page = await self._create_page_with_mocked_data()
            await page.goto(self._get_base_url())
            await page.wait_for_timeout(2000)

            # Check that the page title or heading contains "Oden"
            content = await page.content()
            self.assertIn("Oden", content)
            await page.close()
        finally:
            await self._teardown_playwright()


if __name__ == "__main__":
    unittest.main()
