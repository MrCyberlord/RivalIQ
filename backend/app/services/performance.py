import logging
import math
from time import perf_counter
from uuid import uuid4

from app.intelligence_schemas import Performance, StageTiming

logger = logging.getLogger("uvicorn.error")


class Timings:
    def __init__(self, request_id: str | None = None):
        self.request_id = request_id or uuid4().hex
        self.started = perf_counter()
        self.stages: list[StageTiming] = []

    def record(self, stage: str, started: float, outcome: str, metadata: dict | None = None):
        values = {}
        metadata = metadata or {}
        for upstream, field in (("total_duration", "total_ms"), ("load_duration", "load_ms"),
                                ("prompt_eval_duration", "prompt_eval_ms"), ("eval_duration", "generation_ms")):
            value = metadata.get(upstream)
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                values[field] = round(value / 1_000_000, 3)
        for upstream, field in (("prompt_eval_count", "prompt_tokens"), ("eval_count", "generated_tokens")):
            value = metadata.get(upstream)
            if type(value) is int and value >= 0:
                values[field] = value
        if values.get("generation_ms") and "generated_tokens" in values:
            values["tokens_per_second"] = round(values["generated_tokens"] * 1000 / values["generation_ms"], 2)
        entry = StageTiming(stage=stage, elapsed_ms=round((perf_counter() - started) * 1000, 3), outcome=outcome, **values)
        self.stages.append(entry)
        # Explicit allowlist: no URLs, query text, model content, exception strings or credentials.
        logger.info("rivaliq_timing request_id=%s %s", self.request_id, entry.model_dump_json())

    def finish(self, outcome: str) -> Performance:
        total = round((perf_counter() - self.started) * 1000, 3)
        logger.info("rivaliq_request request_id=%s outcome=%s total_ms=%.3f", self.request_id, outcome, total)
        return Performance(request_id=self.request_id, total_ms=total, stages=self.stages)
