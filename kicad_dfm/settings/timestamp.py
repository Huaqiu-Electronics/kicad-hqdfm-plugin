import logging
from datetime import datetime
import sys
import os

class TimeStamp:
    def __init__(self) -> None:
        # 初始化日志配置
        self._setup_logging()

    def _setup_logging(self):
        try:
            # 获取当前工程目录
            current_dir = os.path.dirname(os.path.abspath(__file__))
            log_file_path = os.path.join(current_dir, "plugin.log")
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(levelname)s - %(message)s",
                datefmt=None,  # 使用自定义格式，因此这里设置为None
                filename=log_file_path,
                filemode="a",  # 追加模式
            )
        except Exception as e:
            logging.basicConfig(
                level=logging.INFO, format="%(message)s", stream=sys.stdout
            )
            logging.error(f"failed to set log file: {e}")

    def log(self, message: str, level: str = "info"):
        # 将level参数转换为小写，确保与logging模块定义的级别匹配
        level = level.lower()
        if level == "info":
            logging.info(message)
        elif level == "warning":
            logging.warning(message)
        elif level == "error":
            logging.error(message)
        elif level == "debug":
            logging.debug(message)
        else:
            print(f"Invalid log level: {level}. Defaulting to INFO.")
            logging.info(message)
