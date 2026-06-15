import os


def get_key(key: str) -> str:
    value = os.getenv(key)
    if value is None:
        raise KeyError(f"Missing required environment variable: {key}")
    return value
