import httpx


class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self, token: str):
        self._token = token
        self._http = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    async def get(self, path: str, accept: str | None = None) -> str:
        headers = {}
        if accept:
            headers["Accept"] = accept
        response = await self._http.get(path, headers=headers)
        response.raise_for_status()
        return response.text

    async def get_json(self, path: str) -> dict:
        response = await self._http.get(path)
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, json_data: dict) -> dict:
        response = await self._http.post(path, json=json_data)
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self._http.aclose()
