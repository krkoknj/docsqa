"""ragas 0.4.3 imports Vertex AI classes that langchain-community 0.4 removed.

ragas only uses them in isinstance() checks, so empty placeholder classes are enough.
Import this module before anything from ragas.
"""

import sys
import types

import langchain_community.llms as community_llms

try:
    import langchain_community.chat_models.vertexai  # noqa: F401
except ModuleNotFoundError:
    shim = types.ModuleType("langchain_community.chat_models.vertexai")
    shim.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules[shim.__name__] = shim

try:
    community_llms.VertexAI  # noqa: B018
except (ImportError, AttributeError):
    community_llms.VertexAI = type("VertexAI", (), {})
