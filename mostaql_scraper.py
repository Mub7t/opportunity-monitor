"""
Standalone Mostaql scraper.

Run:
    python3 mostaql_scraper.py
"""

import logging
import re

from playwright.sync_api import sync_playwright


MOSTAQL_PROJECTS_URL = "https://mostaql.com/projects"
PAGE_LOAD_TIMEOUT_MS = 60_000
PROJECT_LIMIT = 10


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _normalize_space(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _parse_proposals_count(text: str | None) -> int | None:
    clean = _normalize_space(text)
    if not clean:
        return None
    if "أضف أول عرض" in clean:
        return 0
    if "عرضان" in clean:
        return 2
    digits = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    match = re.search(r"(\d+)\s*(?:عرض|عروض)", clean.translate(digits))
    if match:
        return int(match.group(1))
    return None


def scrape_mostaql_projects(limit: int = PROJECT_LIMIT) -> list[dict]:
    """Scrape visible Mostaql projects and return normalized dictionaries."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            locale="ar-SA",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        log.info("Opening %s", MOSTAQL_PROJECTS_URL)
        page.goto(MOSTAQL_PROJECTS_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(".project-row", timeout=PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_timeout(1_000)

        rows = page.evaluate(
            """
            (limit) => {
                const clean = (text) => (text || '').replace(/\\s+/g, ' ').trim();
                const visibleRows = Array.from(document.querySelectorAll('.project-row'))
                    .filter((row) => row.getClientRects().length > 0)
                    .slice(0, limit);

                return visibleRows.map((row) => {
                    const titleLink = row.querySelector('h2 a[href*="/project/"]');
                    const descLink = row.querySelector('a.details-url');
                    const timeEl = row.querySelector('time[itemprop="datePublished"], time');
                    const metaItems = Array.from(row.querySelectorAll('.project__meta li'))
                        .map((li) => clean(li.innerText));
                    const proposalsText = metaItems.find((text) =>
                        text.includes('عرض') || text.includes('عروض')
                    ) || '';
                    const budgetEl = row.querySelector(
                        '[class*="budget"], [data-testid*="budget"], .project-budget'
                    );

                    return {
                        source: 'mostaql',
                        title: clean(titleLink ? titleLink.innerText : ''),
                        url: titleLink ? new URL(titleLink.getAttribute('href'), location.origin).href : '',
                        description_preview: clean(descLink ? descLink.innerText : ''),
                        budget: clean(budgetEl ? budgetEl.innerText : ''),
                        proposals_text: proposalsText,
                        published_date: clean(timeEl ? timeEl.innerText : ''),
                        published_datetime: timeEl ? (timeEl.getAttribute('datetime') || '') : '',
                        raw_text: row.innerText || '',
                    };
                });
            }
            """,
            limit,
        )

        browser.close()

    projects: list[dict] = []
    for project in rows:
        proposals_count = _parse_proposals_count(project.pop("proposals_text", ""))
        projects.append({
            "source": "mostaql",
            "title": _normalize_space(project.get("title")),
            "url": project.get("url", ""),
            "description_preview": _normalize_space(project.get("description_preview")),
            "budget": _normalize_space(project.get("budget")),
            "proposals_count": proposals_count,
            "published_date": _normalize_space(
                project.get("published_datetime") or project.get("published_date")
            ),
            "raw_text": project.get("raw_text", ""),
        })

    for i, project in enumerate(projects[:3]):
        log.info(
            "DEBUG Mostaql project[%d]: title=%r | url=%s | budget=%r | proposals=%r | published=%r | raw_text_first300=%r",
            i,
            project["title"],
            project["url"],
            project["budget"],
            project["proposals_count"],
            project["published_date"],
            project["raw_text"][:300].replace("\n", "↵"),
        )

    return projects


def _print_projects(projects: list[dict]) -> None:
    print(f"Total projects found: {len(projects)}")
    print("=" * 80)
    for i, project in enumerate(projects, start=1):
        print(f"{i}. {project['title']}")
        print(f"   Source: {project['source']}")
        print(f"   URL: {project['url']}")
        print(f"   Published: {project['published_date'] or 'N/A'}")
        print(f"   Proposals: {project['proposals_count'] if project['proposals_count'] is not None else 'N/A'}")
        print(f"   Budget: {project['budget'] or 'N/A'}")
        print(f"   Description: {project['description_preview']}")
        print(f"   Raw text: {_normalize_space(project['raw_text'])[:300]}")
        print("-" * 80)


if __name__ == "__main__":
    _print_projects(scrape_mostaql_projects())
