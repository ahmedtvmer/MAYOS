# scripts/verify_prefix_cache.py
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from agent.assistant_graph import STATIC_SYSTEM_CORE
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger
from utils.model_downloader import llm


logger = MyosLogger().get_logger(__name__)

db = DatabaseManager()
db.switch_user("ahmed")
telemetry = db.get_compact_telemetry()

system_prompt = f"{STATIC_SYSTEM_CORE}\n\n[COACHING DIRECTIVES]\nTone: Direct\n\n{telemetry}"

# Turn 1: Cold Prefill
msg1 = HumanMessage(content="What is the primary driver of hypertrophy?")
res1 = llm.invoke([SystemMessage(content=system_prompt), msg1])

meta1 = res1.response_metadata
logger.info("--- TURN 1 (COLD EVALUATION) ---")
logger.info(f"Prompt Tokens Evaluated (prompt_eval_count): {meta1.get('prompt_eval_count')}")
logger.info(f"Tokens Generated (eval_count):              {meta1.get('eval_count')}")
logger.info(f"Prompt Eval Duration:                       {meta1.get('prompt_eval_duration', 0) / 1e9:.3f}s")
logger.info(f"Generation Duration:                        {meta1.get('eval_duration', 0) / 1e9:.3f}s")

# Turn 2: Warm Cache Hit (Identical System Prefix + Dialogue Tail)
msg2_history = AIMessage(content=res1.content)
msg2_new = HumanMessage(content="How does that apply to lengthened position squats?")

res2 = llm.invoke([
    SystemMessage(content=system_prompt),
    msg1,
    msg2_history,
    msg2_new
])

meta2 = res2.response_metadata
logger.info("\n--- TURN 2 (WARM CACHE EVALUATION) ---")
logger.info(f"Prompt Tokens Evaluated (prompt_eval_count): {meta2.get('prompt_eval_count')}")
logger.info(f"Tokens Generated (eval_count):              {meta2.get('eval_count')}")
logger.info(f"Prompt Eval Duration:                       {meta2.get('prompt_eval_duration', 0) / 1e9:.3f}s")
logger.info(f"Generation Duration:                        {meta2.get('eval_duration', 0) / 1e9:.3f}s")