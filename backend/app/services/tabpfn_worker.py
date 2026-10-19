"""One hosted fit/predict operation, isolated from the API's async loop and telemetry."""
import contextlib
import io
import json
import os
import re
import sys


def run(table):
    try:
        # Public SDK API, never browser/interactive login or token-file persistence.
        import httpx
        import numpy as np
        import pandas as pd
        from tabpfn_client import TabPFNRegressor, set_access_token
        set_access_token(os.environ["TABPFN_API_KEY"])
        model = TabPFNRegressor(n_estimators=4, categorical_features_indices=[0, 1, 3, 5],
                               api_mode="sync", text_handling="simple", random_state=0)
        train = pd.DataFrame(table["train"], columns=table["columns"])
        target = pd.DataFrame(table["target"], columns=table["columns"])
        for field in ("brand", "category", "material", "source_engine"):
            categories = sorted(set(train[field]) | set(target[field]))
            train[field] = pd.Categorical(train[field], categories=categories)
            target[field] = pd.Categorical(target[field], categories=categories)
        model.fit(train, np.asarray(table["prices"], dtype=float))
        prediction = np.asarray(model.predict(target))
        if prediction.shape != (1,) or prediction.dtype.kind not in "fiu" or not np.isfinite(prediction[0]) or prediction[0] <= 0:
            return {"status": "unavailable", "code": "invalid_prediction"}
        return {"status": "predicted", "value": float(prediction[0])}
    except ImportError:
        return {"status": "unavailable", "code": "sdk_missing"}
    except Exception as error:
        # Inspect only exception classes/status codes, never return/log provider text.
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        # SDK 0.6.1 wraps HTTP errors as RuntimeError("... [HTTP NNN] ...").
        # Read only the numeric marker; never surface provider error messages.
        marker = re.search(r"\[HTTP (\d{3})\]", str(error))
        if status is None and marker:
            status = int(marker.group(1))
        if status in (401, 403):
            code = "authentication"
        elif status in (402, 429):
            code = "quota"
        elif status in (408, 504) or isinstance(error, (httpx.TimeoutException, TimeoutError)):
            code = "timeout"
        elif isinstance(error, httpx.TransportError):
            code = "network"
        else:
            code = "sdk_error"
        return {"status": "unavailable", "code": code}


if __name__ == "__main__":
    try:
        table = json.load(sys.stdin)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = run(table)
        print(json.dumps(result, allow_nan=False))
    except Exception:
        print('{"status":"unavailable","code":"sdk_error"}')
