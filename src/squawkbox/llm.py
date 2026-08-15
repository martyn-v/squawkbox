from langchain_ollama import ChatOllama
from langchain_core.language_models import BaseChatModel


def default_model() -> BaseChatModel:
    return ChatOllama(
        model="gemma4:31b",
        temperature=0,
        format="json",
        reasoning=False,
        client_kwargs={"timeout": 30},
    )
