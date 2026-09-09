## # View real-time engine telemetry streaming in the background
# tail -f logs/myos.log | grep "\[TELEMETRY\]"

# # Filter strictly for CPU degradation warnings or thermal throttling
# grep "\[PERF DEGRADATION\]" logs/myos.log

import re
import statistics
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)
LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "myos.log"


def analyze_logs():
    if not LOG_PATH.is_file():
        logger.error("No log file found.")
        return

    ttft_values = []
    tps_values = []

    pattern = re.compile(r"TTFT:\s*([\d\.]+)ms.*?Speed:\s*([\d\.]+)\s*TPS")
    for line in LOG_PATH.read_text().splitlines():
        match = pattern.search(line)
        if match:
            ttft_values.append(float(match.group(1)))
            tps_values.append(float(match.group(2)))

    if not tps_values:
        logger.error("No LLM generation events recorded yet.")
        return

    logger.info("=" * 50)
    logger.info("⚡ MYOS INTERNAL ENGINE HEALTH REPORT")
    logger.info("=" * 50)
    logger.info(f"Total Evaluated Turns:   {len(tps_values)}")
    logger.info(f"Average TTFT:            {statistics.mean(ttft_values):.1f} ms")
    logger.info(f"P95 TTFT:                {statistics.quantiles(ttft_values, n=20)[-1]:.1f} ms")
    logger.info(f"Average Throughput:      {statistics.mean(tps_values):.2f} TPS")
    logger.info(f"Min / Max Throughput:    {min(tps_values):.2f} / {max(tps_values):.2f} TPS")
    logger.info("=" * 50)


if __name__ == "__main__":
    analyze_logs()
