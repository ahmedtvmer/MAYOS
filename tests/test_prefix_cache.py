# tests/test_prefix_cache.py
import sys
import time
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
t0 = time.perf_counter()
res1 = llm.invoke([SystemMessage(content=system_prompt), msg1])
t1 = time.perf_counter()

logger.info("--- TURN 1 (COLD EVALUATION) ---")
logger.info(f"Total Turn Time: {t1 - t0:.3f}s")
logger.info(f"Token Metadata:  {res1.response_metadata.get('token_usage', {})}")

# Turn 2: Warm Evaluation
msg2_history = AIMessage(content=res1.content)
msg2_new = HumanMessage(content="How does that apply to lengthened position squats?")

t2 = time.perf_counter()
res2 = llm.invoke([
    SystemMessage(content=system_prompt),
    msg1,
    msg2_history,
    msg2_new
])
t3 = time.perf_counter()

logger.info("\n--- TURN 2 (WARM CACHE EVALUATION) ---")
logger.info(f"Total Turn Time: {t3 - t2:.3f}s")
logger.info(f"Token Metadata:  {res2.response_metadata.get('token_usage', {})}")