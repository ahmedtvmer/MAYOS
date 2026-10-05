import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from pydantic import BaseModel, Field, field_validator

from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn

load_dotenv()

Embedding = os.getenv("EMBEDDING_MODEL", 'BAAI/bge-small-en-v1.5')

# Anchor paths
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

# The seeded Exercise library and local embedding model stay available to the tool.
db: Any = None
embed_model = HuggingFaceEmbeddings(
    model_name=Embedding, model_kwargs={"device": "cpu"}, encode_kwargs={"normalize_embeddings": True}
)


# 1. Define defensive schema for the tool
class SearchExercisesInput(BaseModel):
    query: str = Field(description="Search string describing exercises, equipment, or muscles")

    @field_validator("query", mode="before")
    @classmethod
    def sanitize_query(cls, v):
        # Unpack if the model hallucinates a dict wrapper
        if isinstance(v, dict):
            return v.get("value", str(v))
        return v


# 2. Attach schema to the tool
@tool(args_schema=SearchExercisesInput)
def search_exercises(query: str) -> str:
    """
    Searches the exercise library using semantic search.
    Use this when the user asks for exercise suggestions, alternatives, or movement details.
    """
    query_vector = embed_model.embed_query(query)
    results = db.search_similar_exercises(query_vector, limit=3)
    if not results:
        return "No matching exercises found."

    formatted = []
    for r in results:
        formatted.append(
            f"ID: {r['id']} | Name: {r['name']} | Target: {r['target_muscle']} | Equipment: {r['equipment']}"
        )
    return "\n".join(formatted)


def test_tool_calling(scripted_chat_model: ScriptedChatModel, fresh_store, monkeypatch):
    logger.info("Initializing scripted hosted chat model...")
    monkeypatch.setitem(globals(), "db", fresh_store)

    tools = [search_exercises]
    scripted_chat_model.script(
        ToolCallsTurn(
            calls=[
                {
                    "name": "search_exercises",
                    "args": {"query": "hamstring exercises with a barbell"},
                    "id": "search_exercises_1",
                }
            ]
        )
    )
    llm_with_tools = scripted_chat_model.bind_tools(tools)

    # Test tool invocation
    user_prompt = "Can you recommend some hamstring exercises with a barbell?"
    logger.info(f"Testing tool routing with prompt: '{user_prompt}'")

    response = llm_with_tools.invoke(user_prompt)

    logger.info(f"Raw Response: {response.content}")
    logger.info(f"Tool Calls Detected: {response.tool_calls}")

    if response.tool_calls:
        tool_call = response.tool_calls[0]
        logger.info(f"Calling tool: {tool_call['name']} with args: {tool_call['args']}")

        # Execute the tool
        tool_output = search_exercises.invoke(tool_call["args"])
        logger.info(f"Tool Result:\n{tool_output}")
    else:
        logger.warning("LLM responded directly without triggering the tool.")
