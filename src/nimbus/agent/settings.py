import os

DEFAULT_AGENT_MODEL = "openai/gpt-oss-120b"


def agent_model() -> str:
    return os.environ.get("NIMBUS_AGENT_MODEL", DEFAULT_AGENT_MODEL)


def groq_api_key() -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")
    return key


def pinecone_api_key() -> str:
    key = os.environ.get("PINECONE_API_KEY")
    if not key:
        raise RuntimeError("PINECONE_API_KEY is not set.Put it in .env.")
    return key
