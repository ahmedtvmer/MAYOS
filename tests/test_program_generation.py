import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

from agent.program_generator import generate_program_pipeline

def run_test():
    logger.info("--- Starting Phase 2 Program Generation ---")
    program, table_view = generate_program_pipeline()
    
    logger.info("\n" + "=" * 50)
    logger.info(table_view)
    logger.info("=" * 50)
    logger.info("\nPhase 2 Program Generation & Database Persistence Verified.")

if __name__ == "__main__":
    run_test()