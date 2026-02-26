import time
from urllib.parse import quote_plus
from config import config
from client import GetOnBoardClient
from parser import parse_jobs
from exporter import export_jobs


def run():
    client = GetOnBoardClient()
    all_jobs = []

    for term in config.search_terms:
        print(f"Scraping term: {term}")

        query = quote_plus(term)
        url = f"{config.base_url}?q={query}"

        response = client.get(url)
        jobs = parse_jobs(response.text, term)

        print(f"Found {len(jobs)} jobs for {term}")

        all_jobs.extend(jobs)
        time.sleep(config.delay_between_requests)

    export_jobs(all_jobs, "getonboard_jobs.json")
    print(f"Total jobs scraped: {len(all_jobs)}")


if __name__ == "__main__":
    run()