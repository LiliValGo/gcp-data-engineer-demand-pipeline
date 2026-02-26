from bs4 import BeautifulSoup
from datetime import datetime
from typing import List
from models import Job


def parse_jobs(html: str, search_term: str) -> List[Job]:
    soup = BeautifulSoup(html, "lxml")

    jobs = []

    cards = soup.find_all("article")  # ajustar según HTML real

    for card in cards:
        try:
            title_tag = card.find("h2")
            company_tag = card.find("h3")
            link_tag = card.find("a", href=True)

            if not title_tag or not company_tag or not link_tag:
                continue

            job = Job(
                title=title_tag.text.strip(),
                company=company_tag.text.strip(),
                location=None,
                salary=None,
                url=f"https://www.getonbrd.com{link_tag['href']}",
                description=None,
                search_term=search_term,
                scraped_at=datetime.utcnow()
            )

            jobs.append(job)

        except Exception:
            continue

    return jobs