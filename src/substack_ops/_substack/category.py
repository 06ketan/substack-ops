"""Category lookup — httpx port of NHagar/substack_api/category.py."""

from __future__ import annotations

import time
from typing import Any

from substack_ops._substack._http import shared_client


def list_all_categories() -> list[tuple[str, int]]:
    with shared_client() as client:
        r = client.get("https://substack.com/api/v1/categories")
        r.raise_for_status()
        return [(item["name"], item["id"]) for item in r.json()]


class Category:
    def __init__(self, name: str | None = None, id: int | None = None) -> None:
        if name is None and id is None:
            raise ValueError("Either name or id must be provided")
        self.name = name
        self.id = id
        self._publications: list[dict[str, Any]] | None = None
        if self.name and self.id is None:
            self._lookup_id()
        elif self.id and self.name is None:
            self._lookup_name()

    def __repr__(self) -> str:
        return f"Category(name={self.name!r}, id={self.id!r})"

    def _lookup_id(self) -> None:
        for n, i in list_all_categories():
            if n == self.name:
                self.id = i
                return
        raise ValueError(f"Category name {self.name!r} not found")

    def _lookup_name(self) -> None:
        for n, i in list_all_categories():
            if i == self.id:
                self.name = n
                return
        raise ValueError(f"Category id {self.id!r} not found")

    def _fetch_publications(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        if self._publications is not None and not force_refresh:
            return self._publications
        all_pubs: list[dict[str, Any]] = []
        page = 0
        with shared_client() as client:
            while page <= 20:
                r = client.get(
                    f"https://substack.com/api/v1/category/public/{self.id}/all",
                    params={"page": page},
                )
                r.raise_for_status()
                data = r.json()
                all_pubs.extend(data.get("publications", []))
                if not data.get("more"):
                    break
                page += 1
                time.sleep(0.5)
        self._publications = all_pubs
        return all_pubs

    def get_publications(self) -> list[dict[str, Any]]:
        return self._fetch_publications()

    def get_newsletter_urls(self) -> list[str]:
        return [p.get("base_url") for p in self._fetch_publications() if p.get("base_url")]
