"""Abstract LLM provider contract for structured decision generation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class BaseLLMProvider(ABC):
    """
    Provider surface for async, schema-bound LLM outputs.

    Implementations must return an instance of ``schema`` validated by Pydantic.
    """

    @abstractmethod
    async def generate_decision(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """
        Run the model against ``prompt`` and parse the result into ``schema``.

        Parameters
        ----------
        prompt :
            Instruction / context for the model.
        schema :
            Concrete ``BaseModel`` subclass describing the expected structured response.
        """
        ...
