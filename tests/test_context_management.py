import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))


from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


def test_context_test_suite():
    logger.info("⚡ Starting Context Window & State Management Test Suite...\n")
    test_user = "test_context_trainee"
    
    # Ensure fresh test isolation
    test_db = Path(f"db/users/{test_user}.db")
    if test_db.exists():
        test_db.unlink()
        
    db = DatabaseManager()
    db.switch_user(test_user)
    db.clear_chat_history()

if __name__ == "__main__":
    test_context_test_suite()
