import logging
import sys
import os

class MyosLogger:
    _instance = None

    def __new__(cls, log_file='../logs/myos.log'):
        if cls._instance is None:
            cls._instance = super(MyosLogger, cls).__new__(cls)
            cls._instance._initialize_logger(log_file)
        return cls._instance

    def _initialize_logger(self, log_file):
        # Create the root logger for the application
        self.root_logger = logging.getLogger("myos")
        self.root_logger.setLevel(logging.INFO)

        # Prevent duplicate handlers if instantiated multiple times
        if not self.root_logger.handlers:
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

            # 1. Console Output
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            self.root_logger.addHandler(console_handler)

            # 2. File Output (Critical for LangGraph agent debugging)
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            self.root_logger.addHandler(file_handler)

    def get_logger(self, module_name):
        """
        Returns a child logger. 
        Pass __name__ from the calling file to track where the log came from.
        """
        return logging.getLogger(f"myos.{module_name}")