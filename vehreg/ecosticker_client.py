"""Small public-site client for Thailand ECO Sticker vehicle data.

The ECO Sticker landing-page frontend is a public SPA.  Its published source
map shows that the car detail page calls ``/api/v2/landing-page/{car_id}`` and
uses the returned ``brochure_link`` directly for the Download brochure button.

This module only reproduces those public frontend GET requests.  It does not
bypass authentication, CAPTCHA, or access controls.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Iterator, Optional
from urllib.parse import parse_qs, urlparse

import requests


API_ROOT = "https://api-car.ecosticker.go.th/api"
LIST_URL = f"{API_ROOT}/v2/landing-page/cars"
MARKET_DETAIL_URL = f"{API_ROOT}/v2/landing-page/{{car_id}}"
HOMOLOGATION_DETAIL_URL = f"{API_ROOT}/v1/eco-sticker/public/by-car-id"
DEFAULT_USER_AGENT = "vehicle-market-master/1.0 (+public ECO Sticker landing-page client)"


class ECOStickerClientError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadedBrochure:
    car_id: str
    url: str
    final_url: str
    file_id: str
    path: Path
    sha256: str
    size_bytes: int


def brochure_file_id(url: str) -> str:
    """Return ECO Sticker file_id from a brochure URL when present."""
    try:
        values = parse_qs(urlparse(url).query).get("file_id") or []
        return values[0].strip() if values else ""
    except Exception:
        return ""


def safe_cache_name(car_id: str, brochure_url: str) -> str:
    file_id = brochure_file_id(brochure_url)
    stem = file_id or re.sub(r"[^A-Za-z0-9_.-]+", "_", car_id)
    return f"{stem}.pdf"


class ECOStickerClient:
    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        timeout: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.setdefault("User-Agent", user_agent)
        self.session.headers.setdefault("Accept", "application/json, application/pdf;q=0.9, */*;q=0.8")

    def _json_get(self, url: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ECOStickerClientError(f"GET failed for {url}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ECOStickerClientError(f"Unexpected JSON payload from {url}")
        if payload.get("success") is False:
            raise ECOStickerClientError(str(payload.get("message") or f"ECO Sticker error from {url}"))
        return payload

    def list_cars(
        self,
        *,
        page: int = 1,
        row: int = 100,
        search: str = "",
        sort: str = "",
    ) -> dict[str, Any]:
        return self._json_get(
            LIST_URL,
            params={"page": page, "row": row, "search": search, "sort": sort},
        )

    def iter_cars(self, *, row: int = 100) -> Iterator[dict[str, Any]]:
        """Iterate the whole public vehicle list without relying on fuzzy search.

        The landing-page search has been observed to miss exact model strings,
        so bulk discovery deliberately paginates the full list instead.
        """
        page = 1
        while True:
            payload = self.list_cars(page=page, row=row)
            data = payload.get("data") or {}
            cars = data.get("car_list") or []
            if not isinstance(cars, list):
                raise ECOStickerClientError("ECO Sticker car_list is not a list")
            for car in cars:
                if isinstance(car, dict):
                    yield car
            info = data.get("info") or {}
            total_pages = int(info.get("total_pages") or 0)
            current_page = int(info.get("current_page") or page)
            if not cars or current_page >= total_pages:
                break
            page += 1

    def get_market_detail(self, car_id: str) -> dict[str, Any]:
        """Fetch the same V2 object used by the public car-detail page."""
        car_id = str(car_id).strip()
        if not car_id:
            raise ValueError("car_id is required")
        return self._json_get(MARKET_DETAIL_URL.format(car_id=car_id))

    def get_homologation_detail(self, car_id: str) -> dict[str, Any]:
        return self._json_get(HOMOLOGATION_DETAIL_URL, params={"car_id": car_id})

    def get_brochure_link(self, car_id: str) -> str:
        payload = self.get_market_detail(car_id)
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return ""
        return str(data.get("brochure_link") or "").strip()

    def download_brochure(
        self,
        car_id: str,
        destination_dir: Path | str,
        *,
        overwrite: bool = False,
    ) -> Optional[DownloadedBrochure]:
        """Download the brochure exposed by the public detail page.

        Returns ``None`` when the vehicle has no brochure link.  The response is
        validated as a PDF and hashed so multiple ECO records that point at the
        same brochure can be deduplicated by the caller.
        """
        brochure_url = self.get_brochure_link(car_id)
        if not brochure_url:
            return None

        root = Path(destination_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / safe_cache_name(car_id, brochure_url)

        if path.exists() and not overwrite:
            raw = path.read_bytes()
            if not raw.startswith(b"%PDF-"):
                raise ECOStickerClientError(f"Cached brochure is not a PDF: {path}")
            return DownloadedBrochure(
                car_id=car_id,
                url=brochure_url,
                final_url=brochure_url,
                file_id=brochure_file_id(brochure_url),
                path=path,
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=len(raw),
            )

        try:
            response = self.session.get(brochure_url, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ECOStickerClientError(f"Brochure download failed for {car_id}: {exc}") from exc

        raw = response.content
        if not raw.startswith(b"%PDF-"):
            content_type = response.headers.get("Content-Type", "")
            raise ECOStickerClientError(
                f"Brochure for {car_id} is not a PDF "
                f"(status={response.status_code}, content-type={content_type!r})")

        path.write_bytes(raw)
        return DownloadedBrochure(
            car_id=car_id,
            url=brochure_url,
            final_url=str(response.url),
            file_id=brochure_file_id(brochure_url),
            path=path,
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )
