import sys
from pathlib import Path
from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from dotenv import load_dotenv
import os
from pydantic import BaseModel, Field, field_validator
load_dotenv()

Embedding = os.getenv("EMBEDDING_MODEL")
llm = ChatOllama(model=os.getenv("LLM"), temperature=0.0)

# Anchor paths
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from utils.logger import MyosLogger
from database.database_manager import DatabaseManager


logger = MyosLogger().get_logger(__name__)

# Initialize shared components
db = DatabaseManager()
embed_model = HuggingFaceEmbeddings(
    model_name=Embedding,
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
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
    Searches the exercise catalog using semantic search.
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

def test_tool_calling():
    logger.info("Initializing ChatOllama...")

    tools = [search_exercises]
    llm_with_tools = llm.bind_tools(tools)

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
        tool_output = search_exercises.invoke(tool_call['args'])
        logger.info(f"Tool Result:\n{tool_output}")
    else:
        logger.warning("LLM responded directly without triggering the tool.")

if __name__ == "__main__":
    test_tool_calling()