"""Optional SDK adapter tests: no hosted requests, only mocked model/auth calls."""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.tabpfn_worker import run


@pytest.fixture
def sdk(monkeypatch):
    np = pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    monkeypatch.setenv("TABPFN_API_KEY", "secret-test-token")
    monkeypatch.setenv("TABPFN_DISABLE_TELEMETRY", "1")
    model = MagicMock()
    model.predict.return_value = np.array([123.45])
    token = MagicMock()
    constructor = MagicMock(return_value=model)
    monkeypatch.setitem(sys.modules, "tabpfn_client", SimpleNamespace(TabPFNRegressor=constructor, set_access_token=token))
    table = {"columns": ["brand", "category", "capacity_ml", "material", "observation_age_days", "source_engine"],
             "train": [["milton", "bottle", 1000.0, "stainless steel", 1.0, "google_shopping"]] * 30,
             "target": [["milton", "bottle", 1000.0, "stainless steel", 0.0, "google_shopping"]], "prices": list(range(100, 130))}
    return model, token, constructor, table, np


def test_official_public_regressor_api_and_categorical_inputs(sdk):
    model, token, constructor, table, _ = sdk
    assert run(table) == {"status": "predicted", "value": 123.45}
    token.assert_called_once_with("secret-test-token")
    constructor.assert_called_once_with(n_estimators=4, categorical_features_indices=[0, 1, 3, 5],
                                      api_mode="sync", text_handling="simple", random_state=0)
    train, y = model.fit.call_args.args
    assert list(train.columns) == table["columns"]
    assert str(train["brand"].dtype) == "category" and str(train["capacity_ml"].dtype) == "float64"
    assert len(y) == 30 and len(model.predict.call_args.args[0]) == 1


@pytest.mark.parametrize("error,code", [(RuntimeError("Fail to call fit: [HTTP 401] private"), "authentication"),
    (RuntimeError("Fail to call fit: [HTTP 403] private"), "authentication"),
    (RuntimeError("Fail to call predict: [HTTP 429] private"), "quota"),
    (TimeoutError("private"), "timeout"), (RuntimeError("private"), "sdk_error")])
def test_sdk_wrapped_errors_are_classified_without_leaking_messages(sdk, error, code):
    sdk[0].fit.side_effect = error
    assert run(sdk[3]) == {"status": "unavailable", "code": code}


@pytest.mark.parametrize("shape", ["matrix", "multiple", "nan", "bool", "negative"])
def test_hosted_prediction_shape_and_values(sdk, shape):
    model, _, _, table, np = sdk
    values = {"matrix": [[100]], "multiple": [100, 200], "nan": [np.nan], "bool": [True], "negative": [-10]}
    model.predict.return_value = np.asarray(values[shape])
    assert run(table) == {"status": "unavailable", "code": "invalid_prediction"}
