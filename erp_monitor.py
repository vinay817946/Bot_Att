import os
import asyncio
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


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


ERP_LOGIN_URL = "https://erp.lbrce.ac.in/Login/"
ERP_ATTENDANCE_URL = (
    "https://erp.lbrce.ac.in/Discipline/StudentHistory.aspx"
)

USERNAME = os.getenv("LBRCE_USERNAME", "").strip()
PASSWORD = os.getenv("LBRCE_PASSWORD", "").strip()

YEAR = os.getenv("LBRCE_YEAR", "3").strip()
SEM = os.getenv("LBRCE_SEM", "1").strip()


class LBRCEMonitor:

    def __init__(self):

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        self.logged_in = False

    # =========================================================
    # START BROWSER
    # =========================================================

    async def start(self):

        logger.info("Starting browser...")

        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
        headless=True,
   )

        self.context = await self.browser.new_context(
            viewport={
                "width": 1400,
                "height": 900,
            }
        )

        self.page = await self.context.new_page()

        self.page.set_default_timeout(15000)

        logger.info("Browser started.")

    # =========================================================
    # CLOSE BROWSER
    # =========================================================

    async def close(self):

        try:

            if self.context:
                await self.context.close()

            if self.browser:
                await self.browser.close()

            if self.playwright:
                await self.playwright.stop()

        except Exception as exc:

            logger.error(
                "Error closing browser: %s",
                exc,
            )

    # =========================================================
    # LOGIN
    # =========================================================

    async def login(self):

        if not self.page:
            raise RuntimeError(
                "Browser page is not initialized."
            )

        if not USERNAME:
            raise RuntimeError(
                "LBRCE_USERNAME is missing in .env"
            )

        if not PASSWORD:
            raise RuntimeError(
                "LBRCE_PASSWORD is missing in .env"
            )

        logger.info("Opening LBRCE login page...")

        await self.page.goto(
            ERP_LOGIN_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await self.page.wait_for_timeout(2000)

        logger.info(
            "Current URL: %s",
            self.page.url,
        )

        # -----------------------------------------------------
        # Find username
        # -----------------------------------------------------

        username = self.page.locator(
            "input[type='text'], "
            "input[name*='User'], "
            "input[id*='User'], "
            "input[name*='user'], "
            "input[id*='user']"
        ).first

        # -----------------------------------------------------
        # Find password
        # -----------------------------------------------------

        password = self.page.locator(
            "input[type='password'], "
            "input[name*='Pass'], "
            "input[id*='Pass'], "
            "input[name*='pass'], "
            "input[id*='pass']"
        ).first

        if await username.count() == 0:

            raise RuntimeError(
                "Username input was not found."
            )

        if await password.count() == 0:

            raise RuntimeError(
                "Password input was not found."
            )

        logger.info(
            "Username/password fields found."
        )

        await username.fill(USERNAME)

        await password.fill(PASSWORD)

        # -----------------------------------------------------
        # Find Login button
        # -----------------------------------------------------

        login_button = self.page.locator(
            "input[type='submit'], "
            "button[type='submit'], "
            "input[value*='Login'], "
            "button"
        )

        login_clicked = False

        count = await login_button.count()

        for i in range(count):

            try:

                button = login_button.nth(i)

                text = (
                    await button.inner_text()
                ).strip().lower()

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

                    await button.click()

                    login_clicked = True

                    break

            except Exception:
                continue

        if not login_clicked:

            raise RuntimeError(
                "Login button could not be found."
            )

        logger.info(
            "Login button clicked."
        )

        await self.page.wait_for_timeout(5000)

        logger.info(
            "After login URL: %s",
            self.page.url,
        )

        # -----------------------------------------------------
        # Check if still on Login page
        # -----------------------------------------------------

        if "/Login" in self.page.url:

            # Look for common error messages.
            body_text = (
                await self.page.locator(
                    "body"
                ).inner_text()
            )

            logger.error(
                "ERP login appears to have failed."
            )

            logger.error(
                "Login page text:\n%s",
                body_text[:3000],
            )

            await self.page.screenshot(
                path="login_failed.png",
                full_page=True,
            )

            raise RuntimeError(
                "LBRCE login failed. "
                "Check username/password."
            )

        self.logged_in = True

        logger.info(
            "LBRCE login successful."
        )

    # =========================================================
    # OPEN ATTENDANCE PAGE
    # =========================================================

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

        await self.page.wait_for_timeout(3000)

        logger.info(
            "Student History URL: %s",
            self.page.url,
        )

        # -----------------------------------------------------
        # If session expired, ERP redirects to Login.
        # -----------------------------------------------------

        if "/Login" in self.page.url:

            logger.warning(
                "ERP redirected to login page."
            )

            self.logged_in = False

            await self.login()

            await self.page.goto(
                ERP_ATTENDANCE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await self.page.wait_for_timeout(3000)

        if "/Login" in self.page.url:

            raise RuntimeError(
                "Could not open StudentHistory.aspx "
                "because ERP session is not logged in."
            )

        logger.info(
            "Attendance page opened successfully."
        )

    # =========================================================
    # SELECT YEAR
    # =========================================================

    async def select_year(self):

        if not self.page:
            raise RuntimeError(
                "Browser page is not initialized."
            )

        logger.info(
            "Looking for Year dropdown..."
        )

        year_select = self.page.locator(
            "#ContentPlaceHolder1_ddlYear"
        )

        if await year_select.count() == 0:

            raise RuntimeError(
                "Year dropdown "
                "#ContentPlaceHolder1_ddlYear "
                "was not found."
            )

        logger.info(
            "Year dropdown found."
        )

        logger.info(
            "Selecting Year = %s",
            YEAR,
        )

        # -----------------------------------------------------
        # Select year.
        #
        # ASP.NET may trigger an AJAX postback.
        # -----------------------------------------------------

        await year_select.select_option(
            YEAR
        )

        await self.page.wait_for_timeout(
            3000
        )

        logger.info(
            "Year selected."
        )

    # =========================================================
    # SELECT SEMESTER
    # =========================================================

    async def select_semester(self):

        if not self.page:
            raise RuntimeError(
                "Browser page is not initialized."
            )

        logger.info(
            "Looking for Semester dropdown..."
        )

        # Re-locate after AJAX update.
        semester_select = self.page.locator(
            "#ContentPlaceHolder1_ddlsem"
        )

        if await semester_select.count() == 0:

            raise RuntimeError(
                "Semester dropdown "
                "#ContentPlaceHolder1_ddlsem "
                "was not found."
            )

        logger.info(
            "Semester dropdown found."
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

    # =========================================================
    # CLICK ATTENDANCE
    # =========================================================

    async def click_attendance(self):

        if not self.page:
            raise RuntimeError(
                "Browser page is not initialized."
            )

        logger.info(
            "Looking for Attendance button..."
        )

        attendance_button = self.page.locator(
            "#ContentPlaceHolder1_btnAtt"
        )

        if await attendance_button.count() == 0:

            raise RuntimeError(
                "Attendance button "
                "#ContentPlaceHolder1_btnAtt "
                "was not found."
            )

        logger.info(
            "Attendance button found."
        )

        url_before = self.page.url

        logger.info(
            "URL before Attendance: %s",
            url_before,
        )

        # -----------------------------------------------------
        # Click the ASP.NET AJAX button.
        #
        # DO NOT use page.goto() here.
        #
        # The ERP updates the page using AJAX and keeps
        # StudentHistory.aspx as the URL.
        # -----------------------------------------------------

        try:

            async with self.page.expect_response(
                lambda response:
                    response.request.method == "POST"
                    and "StudentHistory.aspx"
                    in response.url,
                timeout=15000,
            ):

                await attendance_button.click()

        except PlaywrightTimeoutError:

            logger.warning(
                "POST response was not captured."
            )

            # The click may still have happened.
            # Continue and inspect the page.

            try:

                await attendance_button.click(
                    timeout=5000
                )

            except Exception:
                pass

        await self.page.wait_for_timeout(
            4000
        )

        url_after = self.page.url

        logger.info(
            "URL after Attendance: %s",
            url_after,
        )

        if url_before == url_after:

            logger.info(
                "URL remained unchanged. "
                "ASP.NET AJAX behavior is correct."
            )

        else:

            logger.warning(
                "URL changed from %s to %s",
                url_before,
                url_after,
            )

        # -----------------------------------------------------
        # Wait for attendance table.
        # -----------------------------------------------------

        table = self.page.locator(
            "#ContentPlaceHolder1_gvStdHistory"
        )

        try:

            await table.wait_for(
                state="visible",
                timeout=15000,
            )

        except PlaywrightTimeoutError:

            logger.error(
                "Attendance table not found."
            )

            await self.save_debug_files(
                "attendance_table_not_found"
            )

            raise RuntimeError(
                "Attendance table not found "
                "after clicking Attendance."
            )

        logger.info(
            "Attendance table found."
        )

    # =========================================================
    # PARSE ATTENDANCE
    # =========================================================

    async def parse_attendance(self):

        if not self.page:
            raise RuntimeError(
                "Browser page is not initialized."
            )

        table = self.page.locator(
            "#ContentPlaceHolder1_gvStdHistory"
        )

        if await table.count() == 0:

            raise RuntimeError(
                "Attendance table does not exist."
            )

        # Get HTML.
        html = await table.inner_html()

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        rows = soup.find_all("tr")

        attendance = []

        # -----------------------------------------------------
        # First row is header.
        # -----------------------------------------------------

        for row in rows[1:]:

            cells = row.find_all("td")

            if len(cells) < 5:
                continue

            values = [
                cell.get_text(
                    " ",
                    strip=True
                )
                for cell in cells
            ]

            try:

                serial_number = values[0]

                subject = values[1]

                classes_held = int(
                    values[2]
                )

                classes_present = int(
                    values[3]
                )

                percentage_text = (
                    values[4]
                    .replace("%", "")
                    .strip()
                )

                percentage = float(
                    percentage_text
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
                    "serial": serial_number,
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
                "Attendance table was found "
                "but no attendance rows could "
                "be extracted."
            )

        return attendance

    # =========================================================
    # GET OVERALL ATTENDANCE
    # =========================================================

    async def get_overall(self):

        if not self.page:
            return None

        element = self.page.locator(
            "#ContentPlaceHolder1_lblAttPercent"
        )

        if await element.count() == 0:

            logger.warning(
                "Overall attendance element "
                "was not found."
            )

            return None

        text = (
            await element.first.inner_text()
        ).strip()

        text = (
            text
            .replace("%", "")
            .strip()
        )

        try:

            return float(text)

        except ValueError:

            logger.warning(
                "Could not parse overall "
                "attendance: %s",
                text,
            )

            return None

    # =========================================================
    # GET MONTHLY ATTENDANCE
    # =========================================================

    async def get_monthly_attendance(self):

        if not self.page:
            return []

        table = self.page.locator(
            "#ContentPlaceHolder1_gvAttMonth"
        )

        if await table.count() == 0:
            return []

        html = await table.inner_html()

        soup = BeautifulSoup(
            html,
            "html.parser"
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
                    strip=True
                )
                for cell in cells
            ]

            try:

                monthly.append(
                    {
                        "month": values[0],
                        "total": int(values[1]),
                        "present": int(values[2]),
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

    # =========================================================
    # MAIN ATTENDANCE FUNCTION
    # =========================================================

    async def get_attendance(self):

        if not self.page:

            await self.start()

        # -----------------------------------------------------
        # Login if necessary.
        # -----------------------------------------------------

        if not self.logged_in:

            await self.login()

        # -----------------------------------------------------
        # Open StudentHistory.aspx
        # -----------------------------------------------------

        await self.open_attendance_page()

        # -----------------------------------------------------
        # Select Year.
        # -----------------------------------------------------

        await self.select_year()

        # -----------------------------------------------------
        # Select Semester.
        # -----------------------------------------------------

        await self.select_semester()

        # -----------------------------------------------------
        # Click Attendance.
        # -----------------------------------------------------

        await self.click_attendance()

        # -----------------------------------------------------
        # Read subject-wise attendance.
        # -----------------------------------------------------

        attendance = await self.parse_attendance()

        # -----------------------------------------------------
        # Read overall attendance.
        # -----------------------------------------------------

        overall = await self.get_overall()

        # -----------------------------------------------------
        # Read monthly attendance.
        # -----------------------------------------------------

        monthly = await self.get_monthly_attendance()

        return {
            "subjects": attendance,
            "overall": overall,
            "monthly": monthly,
        }

    # =========================================================
    # DEBUG FILES
    # =========================================================

    async def save_debug_files(
        self,
        name: str
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
                "Debug files saved: %s.png / %s.html",
                name,
                name,
            )

        except Exception as exc:

            logger.error(
                "Could not save debug files: %s",
                exc,
            )


# =============================================================
# TEST FUNCTION
# =============================================================

async def test_monitor():

    monitor = LBRCEMonitor()

    try:

        await monitor.start()

        result = await monitor.get_attendance()

        print("")
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
            result["overall"]
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


if __name__ == "__main__":

    asyncio.run(
        test_monitor()
    )   