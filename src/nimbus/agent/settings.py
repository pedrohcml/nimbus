import os

DEFAULT_AGENT_MODEL = "gemma4:12b"


def agent_model() -> str:
    return os.environ.get("NIMBUS_AGENT_MODEL") or DEFAULT_AGENT_MODEL


def reasoning_effort() -> str:
    return os.environ.get("NIMBUS_REASONING_EFFORT") or "medium"


def ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1"


def pinecone_api_key() -> str:
    key = os.environ.get("PINECONE_API_KEY")
    if not key:
        raise RuntimeError("PINECONE_API_KEY is not set. Put it in .env.")
    return key


def sampling_options() -> dict[str, float | int]:
    options: dict[str, float | int] = {}
    if value := os.environ.get("NIMBUS_TEMPERATURE"):
        options["temperature"] = float(value)
    if value := os.environ.get("NIMBUS_TOP_P"):
        options["top_p"] = float(value)
    if value := os.environ.get("NIMBUS_SEED"):
        options["seed"] = int(value)
    return options
