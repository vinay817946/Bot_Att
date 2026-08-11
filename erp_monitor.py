import os
import logging
from typing import Optional

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# LOGGING
# =========================================================

logger = logging.getLogger(__name__)


# =========================================================
# ERP CONFIG
# =========================================================

ERP_LOGIN_URL = (
    "https://erp.lbrce.ac.in/Login/"
)

ERP_ATTENDANCE_URL = (
    "https://erp.lbrce.ac.in/"
    "Discipline/StudentHistory.aspx"
)

USERNAME = os.getenv(
    "LBRCE_USERNAME",
    "",
).strip()

PASSWORD = os.getenv(
    "LBRCE_PASSWORD",
    "",
).strip()

YEAR = os.getenv(
    "LBRCE_YEAR",
    "3",
).strip()

SEM = os.getenv(
    "LBRCE_SEM",
    "1",
).strip()


# =========================================================
# MONITOR
# =========================================================

class LBRCEMonitor:

    def __init__(self):

        self.playwright = None

        self.browser: Optional[
            Browser
        ] = None

        self.context: Optional[
            BrowserContext
        ] = None

        self.page: Optional[
            Page
        ] = None

        self.logged_in = False

    # =====================================================
    # START BROWSER
    # =====================================================

    async def start(self):

        if self.browser:

            logger.info(
                "Browser already running."
            )

            return

        logger.info(
            "Starting Playwright browser..."
        )

        self.playwright = (
            await async_playwright().start()
        )

        self.browser = (
            await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                ],
            )
        )

        self.context = (
            await self.browser.new_context(
                viewport={
                    "width": 1400,
                    "height": 900,
                },
                ignore_https_errors=True,
            )
        )

        self.page = (
            await self.context.new_page()
        )

        self.page.set_default_timeout(
            20000
        )

        logger.info(
            "Browser started."
        )

    # =====================================================
    # CLOSE
    # =====================================================

    async def close(self):

        logger.info(
            "Closing Playwright browser..."
        )

        try:

            if self.page:

                try:
                    await self.page.close()
                except Exception:
                    pass

            if self.context:

                try:
                    await self.context.close()
                except Exception:
                    pass

            if self.browser:

                try:
                    await self.browser.close()
                except Exception:
                    pass

            if self.playwright:

                try:
                    await self.playwright.stop()
                except Exception:
                    pass

        except Exception as exc:

            logger.error(
                "Error closing browser: %s",
                exc,
            )

        finally:

            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
            self.logged_in = False

    # =====================================================
    # LOGIN
    # =====================================================

    async def login(self):

        if not self.page:

            raise RuntimeError(
                "Browser page is not initialized."
            )

        if not USERNAME:

            raise RuntimeError(
                "LBRCE_USERNAME is missing."
            )

        if not PASSWORD:

            raise RuntimeError(
                "LBRCE_PASSWORD is missing."
            )

        logger.info(
            "Opening LBRCE login page..."
        )

        await self.page.goto(
            ERP_LOGIN_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await self.page.wait_for_timeout(
            2000
        )

        logger.info(
            "Login URL: %s",
            self.page.url,
        )

        # -------------------------------------------------
        # USERNAME
        # -------------------------------------------------

        username = self.page.locator(
            "input[type='text'], "
            "input[name*='User'], "
            "input[id*='User'], "
            "input[name*='user'], "
            "input[id*='user']"
        ).first

        # -------------------------------------------------
        # PASSWORD
        # -------------------------------------------------

        password = self.page.locator(
            "input[type='password'], "
            "input[name*='Pass'], "
            "input[id*='Pass'], "
            "input[name*='pass'], "
            "input[id*='pass']"
        ).first

        if await username.count() == 0:

            raise RuntimeError(
                "Username field not found."
            )

        if await password.count() == 0:

            raise RuntimeError(
                "Password field not found."
            )

        await username.fill(
            USERNAME
        )

        await password.fill(
            PASSWORD
        )

        # -------------------------------------------------
        # LOGIN BUTTON
        # -------------------------------------------------

        login_button = self.page.locator(
            "input[type='submit'], "
            "button[type='submit'], "
            "input[value*='Login'], "
            "button"
        )

        clicked = False

        count = await login_button.count()

        for i in range(count):

            try:

                button = (
                    login_button.nth(i)
                )

                text = ""

                try:

                    text = (
                        await button.inner_text()
                    ).strip().lower()

                except Exception:

                    pass

                value = (
                    await button.get_attribute(
                        "value"
                    )
                    or ""
                ).lower()

                if (
                    "login" in text
                    or "login" in value
                ):

                    await button.click(
                        timeout=10000
                    )

                    clicked = True

                    break

            except Exception:

                continue

        if not clicked:

            raise RuntimeError(
                "Login button not found."
            )

        logger.info(
            "Login button clicked."
        )

        await self.page.wait_for_timeout(
            5000
        )

        logger.info(
            "After login URL: %s",
            self.page.url,
        )

        if "/Login" in self.page.url:

            body = await self.page.locator(
                "body"
            ).inner_text()

            logger.error(
                "Login failed:\n%s",
                body[:3000],
            )

            await self.save_debug_files(
                "login_failed"
            )

            raise RuntimeError(
                "LBRCE login failed."
            )

        self.logged_in = True

        logger.info(
            "LBRCE login successful."
        )

    # =====================================================
    # OPEN ATTENDANCE PAGE
    # =====================================================

    async def open_attendance_page(self):

        if not self.page:

            raise RuntimeError(
                "Browser page is not initialized."
            )

        logger.info(
            "Opening StudentHistory.aspx..."
        )

        await self.page.goto(
            ERP_ATTENDANCE_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await self.page.wait_for_timeout(
            3000
        )

        logger.info(
            "Student History URL: %s",
            self.page.url,
        )

        # -------------------------------------------------
        # SESSION EXPIRED
        # -------------------------------------------------

        if "/Login" in self.page.url:

            logger.warning(
                "Session expired. Logging in again."
            )

            self.logged_in = False

            await self.login()

            await self.page.goto(
                ERP_ATTENDANCE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await self.page.wait_for_timeout(
                3000
            )

        if "/Login" in self.page.url:

            raise RuntimeError(
                "Could not open StudentHistory.aspx."
            )

        logger.info(
            "Attendance page opened."
        )

    # =====================================================
    # SELECT YEAR
    # =====================================================

    async def select_year(self):

        if not self.page:

            raise RuntimeError(
                "Browser page not initialized."
            )

        logger.info(
            "Looking for Year dropdown..."
        )

        year_select = self.page.locator(
            "#ContentPlaceHolder1_ddlYear"
        )

        await year_select.wait_for(
            state="visible",
            timeout=15000,
        )

        logger.info(
            "Selecting Year = %s",
            YEAR,
        )

        await year_select.select_option(
            YEAR
        )

        await self.page.wait_for_timeout(
            3000
        )

        logger.info(
            "Year selected."
        )

    # =====================================================
    # SELECT SEMESTER
    # =====================================================

    async def select_semester(self):

        if not self.page:

            raise RuntimeError(
                "Browser page not initialized."
            )

        logger.info(
            "Looking for Semester dropdown..."
        )

        semester_select = self.page.locator(
            "#ContentPlaceHolder1_ddlsem"
        )

        await semester_select.wait_for(
            state="visible",
            timeout=15000,
        )

        logger.info(
            "Selecting Semester = %s",
            SEM,
        )

        await semester_select.select_option(
            SEM
        )

        await self.page.wait_for_timeout(
            3000
        )

        logger.info(
            "Semester selected."
        )

    # =====================================================
    # CHECK TABLE
    # =====================================================

    async def attendance_table_exists(self):

        if not self.page:

            return False

        table = self.page.locator(
            "#ContentPlaceHolder1_gvStdHistory"
        )

        try:

            if await table.count() == 0:

                return False

            return await table.is_visible()

        except Exception:

            return False

    # =====================================================
    # CLICK ATTENDANCE
    # =====================================================

    async def click_attendance(self):

        if not self.page:

            raise RuntimeError(
                "Browser page not initialized."
            )

        attendance_button = self.page.locator(
            "#ContentPlaceHolder1_btnAtt"
        )

        if await attendance_button.count() == 0:

            raise RuntimeError(
                "Attendance button not found."
            )

        logger.info(
            "Clicking Attendance..."
        )

        # -------------------------------------------------
        # If table already exists, still click again.
        # The ERP may refresh it through AJAX.
        # -------------------------------------------------

        for attempt in range(1, 4):

            logger.info(
                "Attendance click attempt %s/3",
                attempt,
            )

            try:

                # Re-locate every attempt because
                # ASP.NET can replace the DOM.

                attendance_button = (
                    self.page.locator(
                        "#ContentPlaceHolder1_btnAtt"
                    )
                )

                await attendance_button.wait_for(
                    state="visible",
                    timeout=10000,
                )

                await attendance_button.scroll_into_view_if_needed()

                # -------------------------------------------------
                # Try to observe a POST request.
                # The ERP may use normal ASP.NET POST
                # or asynchronous AJAX.
                # -------------------------------------------------

                try:

                    async with self.page.expect_response(
                        lambda response:
                            response.request.method == "POST"
                            and "StudentHistory.aspx"
                            in response.url,
                        timeout=12000,
                    ):

                        await attendance_button.click(
                            timeout=10000
                        )

                except PlaywrightTimeoutError:

                    logger.warning(
                        "POST response not captured. "
                        "Click may still have completed."
                    )

                    try:

                        await attendance_button.click(
                            timeout=5000
                        )

                    except Exception as exc:

                        logger.warning(
                            "Second click attempt failed: %s",
                            exc,
                        )

                await self.page.wait_for_timeout(
                    3000
                )

                # -------------------------------------------------
                # Check for table.
                # -------------------------------------------------

                table = self.page.locator(
                    "#ContentPlaceHolder1_gvStdHistory"
                )

                try:

                    await table.wait_for(
                        state="visible",
                        timeout=12000,
                    )

                    logger.info(
                        "Attendance table found."
                    )

                    return

                except PlaywrightTimeoutError:

                    logger.warning(
                        "Attendance table not found "
                        "after attempt %s.",
                        attempt,
                    )

                # -------------------------------------------------
                # Sometimes ERP AJAX update finishes late.
                # Wait a little longer before retrying.
                # -------------------------------------------------

                await self.page.wait_for_timeout(
                    3000
                )

                if await self.attendance_table_exists():

                    logger.info(
                        "Attendance table appeared "
                        "after delayed AJAX update."
                    )

                    return

            except Exception as exc:

                logger.warning(
                    "Attendance attempt %s failed: %s",
                    attempt,
                    exc,
                )

            # -----------------------------------------------------
            # On failure, reload StudentHistory page and retry.
            # This is important for the second/third polling cycle.
            # -----------------------------------------------------

            if attempt < 3:

                logger.warning(
                    "Reloading StudentHistory.aspx "
                    "before retry..."
                )

                try:

                    await self.page.goto(
                        ERP_ATTENDANCE_URL,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )

                    await self.page.wait_for_timeout(
                        2500
                    )

                    if "/Login" in self.page.url:

                        self.logged_in = False

                        await self.login()

                        await self.page.goto(
                            ERP_ATTENDANCE_URL,
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )

                        await self.page.wait_for_timeout(
                            2500
                        )

                    await self.select_year()

                    await self.select_semester()

                except Exception as exc:

                    logger.warning(
                        "Could not prepare retry: %s",
                        exc,
                    )

        # -----------------------------------------------------
        # ALL RETRIES FAILED
        # -----------------------------------------------------

        await self.save_debug_files(
            "attendance_table_not_found"
        )

        raise RuntimeError(
            "Attendance table not found after "
            "3 attempts."
        )

    # =====================================================
    # PARSE ATTENDANCE
    # =====================================================

    async def parse_attendance(self):

        if not self.page:

            raise RuntimeError(
                "Browser page not initialized."
            )

        table = self.page.locator(
            "#ContentPlaceHolder1_gvStdHistory"
        )

        if await table.count() == 0:

            raise RuntimeError(
                "Attendance table does not exist."
            )

        html = await table.inner_html()

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        rows = soup.find_all("tr")

        attendance = []

        for row in rows[1:]:

            cells = row.find_all("td")

            if len(cells) < 5:

                continue

            values = [
                cell.get_text(
                    " ",
                    strip=True,
                )
                for cell in cells
            ]

            try:

                serial = values[0]

                subject = values[1]

                classes_held = int(
                    values[2]
                )

                classes_present = int(
                    values[3]
                )

                percentage = float(
                    values[4]
                    .replace(
                        "%",
                        "",
                    )
                    .strip()
                )

            except (
                ValueError,
                IndexError,
            ):

                logger.warning(
                    "Could not parse row: %s",
                    values,
                )

                continue

            attendance.append(
                {
                    "serial": serial,
                    "subject": subject,
                    "classes_held": classes_held,
                    "classes_present": classes_present,
                    "percentage": percentage,
                }
            )

        if not attendance:

            await self.save_debug_files(
                "attendance_empty"
            )

            raise RuntimeError(
                "No attendance rows found."
            )

        logger.info(
            "Parsed %s attendance subjects.",
            len(attendance),
        )

        return attendance

    # =====================================================
    # OVERALL ATTENDANCE
    # =====================================================

    async def get_overall(self):

        if not self.page:

            return None

        element = self.page.locator(
            "#ContentPlaceHolder1_lblAttPercent"
        )

        if await element.count() == 0:

            logger.warning(
                "Overall attendance element not found."
            )

            return None

        text = (
            await element.first.inner_text()
        ).strip()

        text = (
            text
            .replace(
                "%",
                "",
            )
            .strip()
        )

        try:

            return float(text)

        except ValueError:

            logger.warning(
                "Could not parse overall attendance: %s",
                text,
            )

            return None

    # =====================================================
    # MONTHLY ATTENDANCE
    # =====================================================

    async def get_monthly_attendance(self):

        if not self.page:

            return []

        table = self.page.locator(
            "#ContentPlaceHolder1_gvAttMonth"
        )

        if await table.count() == 0:

            return []

        try:

            html = await table.inner_html()

        except Exception:

            return []

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        rows = soup.find_all("tr")

        monthly = []

        for row in rows[1:]:

            cells = row.find_all("td")

            if len(cells) < 4:

                continue

            values = [
                cell.get_text(
                    " ",
                    strip=True,
                )
                for cell in cells
            ]

            try:

                monthly.append(
                    {
                        "month": values[0],
                        "total": int(
                            values[1]
                        ),
                        "present": int(
                            values[2]
                        ),
                        "percentage": float(
                            values[3]
                        ),
                    }
                )

            except (
                ValueError,
                IndexError,
            ):

                continue

        return monthly

    # =====================================================
    # GET ATTENDANCE
    # =====================================================

    async def get_attendance(self):

        if not self.page:

            await self.start()

        if not self.logged_in:

            await self.login()

        # -------------------------------------------------
        # First attempt
        # -------------------------------------------------

        try:

            await self.open_attendance_page()

            await self.select_year()

            await self.select_semester()

            await self.click_attendance()

        except Exception as exc:

            logger.warning(
                "Attendance page attempt failed: %s",
                exc,
            )

            # -------------------------------------------------
            # One complete session reset.
            # -------------------------------------------------

            await self.close()

            await self.start()

            await self.login()

            await self.open_attendance_page()

            await self.select_year()

            await self.select_semester()

            await self.click_attendance()

        # -------------------------------------------------
        # Parse all attendance information.
        # -------------------------------------------------

        subjects = (
            await self.parse_attendance()
        )

        overall = (
            await self.get_overall()
        )

        monthly = (
            await self.get_monthly_attendance()
        )

        return {
            "subjects": subjects,
            "overall": overall,
            "monthly": monthly,
        }

    # =====================================================
    # DEBUG
    # =====================================================

    async def save_debug_files(
        self,
        name: str,
    ):

        if not self.page:

            return

        try:

            await self.page.screenshot(
                path=f"{name}.png",
                full_page=True,
            )

            html = await self.page.content()

            with open(
                f"{name}.html",
                "w",
                encoding="utf-8",
            ) as file:

                file.write(html)

            logger.info(
                "Debug files saved: "
                "%s.png / %s.html",
                name,
                name,
            )

        except Exception as exc:

            logger.error(
                "Debug file error: %s",
                exc,
            )


# =========================================================
# LOCAL TEST
# =========================================================

async def test_monitor():

    monitor = LBRCEMonitor()

    try:

        await monitor.start()

        result = (
            await monitor.get_attendance()
        )

        print()
        print(
            "================================"
        )
        print(
            "LBRCE ATTENDANCE"
        )
        print(
            "================================"
        )

        for item in result["subjects"]:

            print(
                f"{item['subject']}: "
                f"{item['classes_present']}/"
                f"{item['classes_held']} "
                f"({item['percentage']:.2f}%)"
            )

        print(
            "--------------------------------"
        )

        print(
            "Overall:",
            result["overall"],
        )

        print(
            "--------------------------------"
        )

        for month in result["monthly"]:

            print(
                f"{month['month']}: "
                f"{month['present']}/"
                f"{month['total']} "
                f"({month['percentage']:.2f}%)"
            )

        print(
            "================================"
        )

    except Exception as exc:

        logger.exception(
            "Attendance test failed: %s",
            exc,
        )

    finally:

        await monitor.close()


# =========================================================
# TEST ENTRY
# =========================================================

if __name__ == "__main__":

    import asyncio

    asyncio.run(
        test_monitor()
    )
