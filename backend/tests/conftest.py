"""Never initialize real external persistence/telemetry from a developer's .env in tests."""
import os

os.environ["MONGODB_URI"] = ""
os.environ["SENTRY_DSN"] = ""
os.environ["TABPFN_API_KEY"] = ""
