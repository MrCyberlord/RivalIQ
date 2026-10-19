import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_api_key
from app.main import app, get_http_client
from app.services.serpapi import price, product_url


@pytest.fixture
def make_client():
    clients = []

    def create(payload=None, status=200, key="test-key", exception=None):
        def handler(request):
            assert request.url.host == "serpapi.com"
            assert request.url.params["engine"] == "google_shopping"
            assert request.url.params["gl"] == "in"
            assert request.url.params["q"] == "bottle"
            assert request.url.params["api_key"] == "test-key"
            if exception:
                raise exception
            return httpx.Response(status, json=payload)

        # MockTransport ensures every upstream request is intercepted, with no network.
        upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app.dependency_overrides[get_http_client] = lambda: upstream
        app.dependency_overrides[get_api_key] = lambda: key
        client = TestClient(app)
        clients.append(client)
        return client

    yield create
    for client in clients:
        client.close()
    app.dependency_overrides.clear()


def search(client, **changes):
    return client.post("/api/competitors/search", json={"product_name": "bottle", **changes})


def test_health(make_client):
    assert make_client().get("/api/health").json()["status"] == "ok"


def test_normalization_and_limit(make_client):
    row = {"title": "Steel bottle", "price": "₹1,299", "extracted_price": 1299,
           "source": "Shop", "product_link": "https://example.com/bottle", "extensions": ["Steel", 4]}
    response = search(make_client({"shopping_results": [row, row]}), max_results=1)
    assert response.status_code == 200
    items = response.json()["competitors"]
    assert len(items) == 1
    assert items[0] == {"product_name": "Steel bottle", "listed_price": 1299.0, "currency": "INR",
                        "merchant": "Shop", "product_url": "https://example.com/bottle",
                        "features": ["Steel"], "source": "serpapi_google_shopping",
                        "retrieved_at": items[0]["retrieved_at"]}
    assert items[0]["retrieved_at"].endswith("Z")


@pytest.mark.parametrize("bad_price", ["1,200", "free", None, -1, True])
def test_missing_and_malformed_fields(make_client, bad_price):
    item = search(make_client({"shopping_results": [{"extracted_price": bad_price, "price": "$12", "link": "javascript:alert(1)"}]})).json()["competitors"][0]
    assert all(item[field] is None for field in ("product_name", "listed_price", "currency", "merchant", "product_url", "features"))


@pytest.mark.parametrize("payload", [{}, {"shopping_results": []}, {"shopping_results": [None, {}, 3]}])
def test_empty(make_client, payload):
    assert search(make_client(payload)).json() == {"competitors": []}


def test_missing_key(make_client):
    assert search(make_client(key="")).status_code == 503


@pytest.mark.parametrize("status,expected", [(429, 429), (401, 503), (403, 503), (500, 502)])
def test_http_failures(make_client, status, expected):
    response = search(make_client({}, status=status))
    assert response.status_code == expected
    assert "test-key" not in response.text


@pytest.mark.parametrize("payload,expected", [({"error": "You have run out of searches"}, 429),
    ({"error": "secret provider details"}, 502), ([], 502), ({"shopping_results": {}}, 502)])
def test_provider_errors(make_client, payload, expected):
    response = search(make_client(payload))
    assert response.status_code == expected
    assert "secret provider details" not in response.text


@pytest.mark.parametrize("exception,expected", [(httpx.ReadTimeout("secret"), 504), (httpx.ConnectError("secret"), 502)])
def test_network_failures(make_client, exception, expected):
    assert search(make_client(exception=exception)).status_code == expected


@pytest.mark.parametrize("changes", [{"product_name": " "}, {"market": "Atlantis"}, {"currency": "XXX"},
    {"max_results": 0}, {"max_results": 21}, {"max_results": True}, {"unexpected": 1}])
def test_validation(make_client, changes):
    assert search(make_client(), **changes).status_code == 422


def test_cors(make_client):
    client = make_client()
    response = client.options("/api/competitors/search", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    response = client.options("/api/competitors/search", headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in response.headers


def test_nonfinite_price_and_malformed_url():
    assert price(float("nan")) is None
    assert price(float("inf")) is None
    assert product_url({"product_link": "https://[invalid"}) is None


def test_invalid_json(make_client):
    async def invalid_response():
        return httpx.Response(200, text="not json", request=httpx.Request("GET", "https://serpapi.com/search.json"))

    class InvalidClient:
        async def get(self, *args, **kwargs):
            return await invalid_response()

    client = make_client()
    app.dependency_overrides[get_http_client] = lambda: InvalidClient()
    assert search(client).status_code == 502
