"""CHAT_COMPLETIONS dialect adapter - the reference implementation.

The highest-leverage adapter by a wide margin. Spoken by OpenRouter, Groq,
Together, DeepSeek, Mistral, vLLM, LM Studio, Ollama, OpenAI and most
self-hosted stacks - get this one right and 'any provider' is already mostly
true.

Written first; the other adapters follow its shape.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 2 - implement completion, tool calling, JSON mode and streaming
