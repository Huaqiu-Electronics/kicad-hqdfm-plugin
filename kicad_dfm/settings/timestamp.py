import logging
from datetime import datetime
import sys


class TimeStamp:
    def __init__(self) -> None:
        # 初始化日志配置
        self._setup_logging()

    def _setup_logging(self):
        # 设置日志的配置信息
        try:
            log_file_path = "C:\\Users\\haf\\Documents\\KiCad\\8.0\\scripting\\plugins\\kicad-dfm-plugin\\plugin.log"
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(levelname)s - %(message)s",
                datefmt=None,  # 使用自定义格式，因此这里设置为None
                filename=log_file_path,
                filemode="a",  # 追加模式
            )
        except Exception as e:
            # 如果日志配置失败，使用标准输出作为回退
            logging.basicConfig(
                level=logging.INFO, format="%(message)s", stream=sys.stdout
            )
            logging.error(f"日志文件配置失败: {e}")

    def log(self, message: str, level: str = "info"):
        # 将level参数转换为小写，确保与logging模块定义的级别匹配
        level = level.lower()
        # 根据传入的level参数选择不同的日志记录方法
        if level == "info":
            logging.info(message)
        elif level == "warning":
            logging.warning(message)
        elif level == "error":
            logging.error(message)
        elif level == "debug":
            logging.debug(message)
        else:
            # 如果level参数不是有效的日志级别，打印错误并使用默认的info级别
            print(f"Invalid log level: {level}. Defaulting to INFO.")
            logging.info(message)
