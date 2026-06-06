"""Local pipeline trace recording utilities."""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterator
from typing import Any

from ratchet.pipeline.llm import BaseLocalLLM
from ratchet.pipeline.store import LocalStore


class PipelineTraceRecorder:
    """Record local pipeline events, heartbeats, and raw LLM artifacts."""

    def __init__(self, *, store: LocalStore, run_id: str) -> None:
        self.store = store
        self.run_id = run_id
        self._label_stack: list[str] = []
        self.store.ensure_run_debug_paths(run_id)

    def event(
        self,
        event_type: str,
        message: str,
        *,
        level: str = "info",
        phase: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.record_pipeline_event(
            self.run_id,
            event_type=event_type,
            message=message,
            level=level,
            phase=phase,
            payload=payload,
        )

    @contextlib.contextmanager
    def llm_label(self, label: str) -> Iterator[None]:
        self._label_stack.append(label)
        try:
            yield
        finally:
            self._label_stack.pop()

    def current_label(self, fallback: str) -> str:
        return self._label_stack[-1] if self._label_stack else fallback

    def wrap_llm(self, llm: BaseLocalLLM) -> BaseLocalLLM:
        return TracedLocalLLM(llm=llm, recorder=self)


class TracedLocalLLM(BaseLocalLLM):
    """BaseLocalLLM wrapper that records every provider call locally."""

    def __init__(self, *, llm: BaseLocalLLM, recorder: PipelineTraceRecorder) -> None:
        self._llm = llm
        self._recorder = recorder
        self.provider = getattr(llm, "provider", "unknown")
        self.default_generation_model = getattr(llm, "default_generation_model", "")

    @contextlib.contextmanager
    def llm_label(self, label: str) -> Iterator[None]:
        with self._recorder.llm_label(label):
            yield

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        label = self._recorder.current_label("embed_documents")
        started = time.perf_counter()
        prompt_text = json.dumps({"texts": texts}, indent=2, ensure_ascii=False)
        try:
            vectors = self._llm.embed_documents(texts)
        except Exception as exc:
            self._recorder.store.record_llm_call(
                self._recorder.run_id,
                label=label,
                provider=self.provider,
                model=getattr(self._llm, "embedding_model", ""),
                call_type="embedding",
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="error",
                prompt_text=prompt_text,
                error=f"{type(exc).__name__}: {exc}",
                payload={"text_count": len(texts)},
            )
            raise
        response_text = json.dumps(
            {
                "vector_count": len(vectors),
                "dimensions": len(vectors[0]) if vectors else 0,
                "vectors": vectors,
            },
            indent=2,
            ensure_ascii=False,
        )
        self._recorder.store.record_llm_call(
            self._recorder.run_id,
            label=label,
            provider=self.provider,
            model=getattr(self._llm, "embedding_model", ""),
            call_type="embedding",
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="ok",
            prompt_text=prompt_text,
            response_text=response_text,
            payload={"text_count": len(texts)},
        )
        return vectors

    def generate_text(self, prompt: str, *, model: str | None = None) -> str:
        label = self._recorder.current_label("generate_text")
        selected_model = model or self.default_generation_model
        started = time.perf_counter()
        try:
            response = self._llm.generate_text(prompt, model=model)
        except Exception as exc:
            self._recorder.store.record_llm_call(
                self._recorder.run_id,
                label=label,
                provider=self.provider,
                model=selected_model,
                call_type="generation",
                duration_ms=int((time.perf_counter() - started) * 1000),
                status="error",
                prompt_text=prompt,
                error=f"{type(exc).__name__}: {exc}",
                payload={"prompt_chars": len(prompt)},
            )
            raise
        self._recorder.store.record_llm_call(
            self._recorder.run_id,
            label=label,
            provider=self.provider,
            model=selected_model,
            call_type="generation",
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="ok",
            prompt_text=prompt,
            response_text=response,
            payload={"prompt_chars": len(prompt), "response_chars": len(response)},
        )
        return response
