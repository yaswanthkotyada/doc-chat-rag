import logging
from typing import AsyncGenerator, Dict, List, Optional
from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base exception for LLM service errors."""
    pass


class LLMConfigurationError(LLMError):
    """Raised when LLM configuration/key is missing or invalid."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when rate limits are exceeded."""
    pass


class LLMSafetyError(LLMError):
    """Raised when safety or policy blocks are triggered."""
    pass


def _sanitize_message(message: str) -> str:
    """Ensure the API key is never leaked in error messages or logs."""
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY in message:
        return message.replace(settings.GEMINI_API_KEY, "[REDACTED]")
    return message


class GeminiLLMService:
    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.default_model = default_model or settings.GEMINI_MODEL
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        if not self.api_key:
            raise LLMConfigurationError("Gemini API key is not configured. Please set GEMINI_API_KEY.")
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def stream_chat(
        self,
        system_instruction: str,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream text response from Gemini given conversation history.
        Each message in `messages` must be a dict: {"role": "user"|"assistant", "content": "..."}.
        """
        model_name = model or self.default_model

        try:
            client = self._get_client()
        except LLMConfigurationError as e:
            raise e

        # Construct multi-turn contents for Gemini SDK
        contents: List[types.Content] = []
        for msg in messages:
            role = "model" if msg.get("role") in ("assistant", "model") else "user"
            content_text = msg.get("content", "")
            if content_text:
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=content_text)]
                    )
                )

        if not contents:
            raise LLMError("Cannot call LLM with empty messages list.")

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
        )

        try:
            stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=config,
            )

            async for chunk in stream:
                # Check for finish reasons like safety blocks mid-stream
                if chunk.candidates:
                    for candidate in chunk.candidates:
                        if candidate.finish_reason:
                            reason = str(candidate.finish_reason).upper()
                            if "SAFETY" in reason:
                                raise LLMSafetyError("Response was interrupted due to content safety policies.")
                            elif "RECITATION" in reason:
                                raise LLMSafetyError("Response was interrupted due to recitation policy.")

                if chunk.text:
                    yield chunk.text

        except APIError as e:
            err_msg = _sanitize_message(str(e.message if hasattr(e, "message") else e))
            code = getattr(e, "code", None)
            logger.error("Gemini APIError encountered: code=%s, message=%s", code, err_msg)

            if code == 400:
                raise LLMConfigurationError("Invalid Gemini request or invalid API key.") from e
            elif code == 429:
                raise LLMRateLimitError("Gemini rate limit exceeded. Please try again shortly.") from e
            else:
                raise LLMError(f"Gemini API returned error: {err_msg}") from e

        except (LLMError, LLMSafetyError, LLMRateLimitError, LLMConfigurationError):
            raise

        except Exception as e:
            err_msg = _sanitize_message(str(e))
            logger.error("Unexpected error in GeminiLLMService: %s", err_msg)
            raise LLMError("An unexpected error occurred while communicating with the AI service.") from e


# Singleton service instance
llm_service = GeminiLLMService()

