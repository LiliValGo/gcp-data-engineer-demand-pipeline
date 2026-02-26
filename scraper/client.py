import requests
from tenacity import retry, stop_after_attempt, wait_fixed
from config import config


class GetOnBoardClient:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent
        })

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get(self, url: str) -> requests.Response:
        response = self.session.get(url, timeout=config.timeout)
        response.raise_for_status()
        return response