"""CI-only server entrypoint because CI has no hosted-model key."""

from svc import llm


async def skip_hosted_model_warmup() -> None:
    """Allow API readiness to cover the locally exercised service in CI."""


llm.warmup_llm = skip_hosted_model_warmup


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("svc.app:app", host="0.0.0.0", port=8000, workers=1)
