from pathlib import Path

from vehreg.ecosticker_client import (
    ECOStickerClient,
    brochure_file_id,
)


CAR_ID = "98c1d7de-79db-4581-b332-69abe657a532"
BROCHURE = "https://api-car.ecosticker.go.th/api/v1/file/data?file_id=d086cd15-ea65-4b25-ab6f-80ffb2071a31"


class FakeResponse:
    def __init__(self, *, payload=None, content=b"", url="https://example.test/final", status=200, headers=None):
        self._payload = payload
        self.content = content
        self.url = url
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert self.responses, f"unexpected GET {url}"
        return self.responses.pop(0)


def test_v2_market_detail_is_source_of_brochure_link():
    session = FakeSession([
        FakeResponse(payload={"success": True, "data": {"brochure_link": BROCHURE}}),
    ])
    client = ECOStickerClient(session=session)
    assert client.get_brochure_link(CAR_ID) == BROCHURE
    assert session.calls[0][0].endswith(f"/api/v2/landing-page/{CAR_ID}")


def test_download_brochure_follows_public_link_validates_pdf_and_hashes(tmp_path: Path):
    session = FakeSession([
        FakeResponse(payload={"success": True, "data": {"brochure_link": BROCHURE}}),
        FakeResponse(content=b"%PDF-1.7\nmock", url="https://object-store.test/file.pdf"),
    ])
    client = ECOStickerClient(session=session)
    result = client.download_brochure(CAR_ID, tmp_path)

    assert result is not None
    assert result.file_id == "d086cd15-ea65-4b25-ab6f-80ffb2071a31"
    assert result.final_url == "https://object-store.test/file.pdf"
    assert result.path.read_bytes().startswith(b"%PDF-")
    assert len(result.sha256) == 64
    assert session.calls[1][1]["allow_redirects"] is True


def test_full_list_pagination_does_not_depend_on_search():
    session = FakeSession([
        FakeResponse(payload={
            "success": True,
            "data": {"car_list": [{"id": "a"}], "info": {"current_page": 1, "total_pages": 2}},
        }),
        FakeResponse(payload={
            "success": True,
            "data": {"car_list": [{"id": "b"}], "info": {"current_page": 2, "total_pages": 2}},
        }),
    ])
    client = ECOStickerClient(session=session)
    assert [x["id"] for x in client.iter_cars(row=100)] == ["a", "b"]
    assert session.calls[0][1]["params"]["search"] == ""
    assert session.calls[1][1]["params"]["page"] == 2


def test_brochure_file_id_parser():
    assert brochure_file_id(BROCHURE) == "d086cd15-ea65-4b25-ab6f-80ffb2071a31"
    assert brochure_file_id("https://example.test/no-id.pdf") == ""
