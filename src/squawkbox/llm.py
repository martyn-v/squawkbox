from langchain_ollama import ChatOllama
from langchain_core.language_models import BaseChatModel
from typing import Literal

DEFAULT_MODEL = "ollama/gemma4:31b"
DEFAULT_MODEL_TEMPERATURE = 0.5
DEFAULT_TIMEOUT_S = 30


def create_model(
    model: str = DEFAULT_MODEL,
    temperature: float | None = DEFAULT_MODEL_TEMPERATURE,
    format: Literal["json"] | None = None,
    reasoning: bool = False,
) -> BaseChatModel:
    provider, _, model_name = model.partition("/")

    if provider == "ollama" and model_name:
        return ChatOllama(
            model=model_name,
            temperature=temperature,
            format=format,
            reasoning=reasoning,
            client_kwargs={"timeout": DEFAULT_TIMEOUT_S},
        )

    raise ValueError(f"Unsupported model: {model}")
