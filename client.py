import os
import sys
import base64
import time
import requests
from dotenv import load_dotenv

load_dotenv()

_RETRYABLE = {429, 500, 502, 503, 504}


class ADOClient:
    """Thin wrapper around the Azure DevOps REST API."""

    def __init__(self, max_retries: int = 4, backoff_base: float = 2.0):
        self.org = os.getenv("ADO_ORG")
        self.project = os.getenv("ADO_PROJECT")
        self.repo = os.getenv("ADO_REPO")  # optional — only needed for single-repo commands
        pat = os.getenv("ADO_PAT")
        self.max_retries = max_retries
        self.backoff_base = backoff_base

        if not all([self.org, self.project, pat]):
            raise EnvironmentError(
                "Missing required env vars: ADO_ORG, ADO_PROJECT, ADO_PAT. "
                "Copy .env.example to .env and fill in values."
            )

        token = base64.b64encode(f":{pat}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }
        self.base_url = f"https://dev.azure.com/{self.org}/{self.project}/_apis"
        self.org_base_url = f"https://dev.azure.com/{self.org}/_apis"

    def _request(self, url: str, params: dict = None) -> dict:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
            except requests.Timeout:
                wait = self.backoff_base ** attempt
                sys.stderr.write(
                    f"\n  [timeout] No response in 30s, retrying in {wait:.0f}s "
                    f"(attempt {attempt + 1}/{self.max_retries})...\n"
                )
                sys.stderr.flush()
                if attempt < self.max_retries:
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"ADO API timed out after {self.max_retries} retries for {url}")

            if response.ok:
                try:
                    return response.json()
                except ValueError:
                    raise RuntimeError(
                        f"ADO API returned non-JSON for {url}\n"
                        f"Response: {response.text[:500]}"
                    )

            if response.status_code in _RETRYABLE and attempt < self.max_retries:
                wait = self.backoff_base ** attempt
                sys.stderr.write(
                    f"  [{response.status_code}] Retrying in {wait:.0f}s "
                    f"(attempt {attempt + 1}/{self.max_retries})...\n"
                )
                sys.stderr.flush()
                time.sleep(wait)
                last_error = response
                continue

            raise RuntimeError(
                f"ADO API error {response.status_code} for {url}\n"
                f"Response: {response.text[:500]}"
            )

        raise RuntimeError(
            f"ADO API error {last_error.status_code} after {self.max_retries} retries for {url}"
        )

    def get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        return self._request(url, {**(params or {}), "api-version": "7.1"})

    def org_get(self, path: str, params: dict = None) -> dict:
        """GET against the org-level API (no project in URL)."""
        url = f"{self.org_base_url}{path}"
        return self._request(url, {**(params or {}), "api-version": "7.1"})

    def post(self, path: str, body: dict) -> dict:
        import requests as req
        url = f"{self.base_url}{path}"
        params = {"api-version": "7.1"}
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = req.post(url, headers=self.headers, params=params, json=body, timeout=30)
            except req.Timeout:
                wait = self.backoff_base ** attempt
                sys.stderr.write(f"\n  [timeout] Retrying in {wait:.0f}s...\n")
                sys.stderr.flush()
                if attempt < self.max_retries:
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"ADO API timed out for {url}")
            if response.ok:
                try:
                    return response.json()
                except ValueError:
                    raise RuntimeError(f"ADO API returned non-JSON for {url}\nResponse: {response.text[:500]}")
            if response.status_code in _RETRYABLE and attempt < self.max_retries:
                wait = self.backoff_base ** attempt
                sys.stderr.write(f"  [{response.status_code}] Retrying in {wait:.0f}s...\n")
                sys.stderr.flush()
                time.sleep(wait)
                last_error = response
                continue
            raise RuntimeError(f"ADO API error {response.status_code} for {url}\nResponse: {response.text[:500]}")
        raise RuntimeError(f"ADO API error {last_error.status_code} after {self.max_retries} retries for {url}")

    def get_paginated(self, path: str, params: dict = None, key: str = "value", label: str = None) -> list:
        results = []
        skip = 0
        top = 100
        while True:
            page_params = {**(params or {}), "$top": top, "$skip": skip}
            if label:
                sys.stderr.write(f"  [{label}] fetching records {skip + 1}–{skip + top}...\n")
                sys.stderr.flush()
            data = self.get(path, page_params)
            items = data.get(key, [])
            results.extend(items)
            if len(items) < top:
                break
            skip += top
        return results

