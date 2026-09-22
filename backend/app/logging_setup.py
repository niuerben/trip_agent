"""把控制台日志同时持久化到 backend/logs/ 下的按日文件。

后端诊断信息几乎都用 ``print()`` 输出到 stdout，uvicorn 的访问/错误日志走
logging 模块到 stderr。这里用一个 Tee 把 stdout/stderr 同时转发到共享文件句柄，
再把同一句柄挂到 uvicorn 的 logger 上，保证两类日志都能落盘且只落一次。

只记录状态/耗时/错误摘要——各调用方已约定不打印 API Key、JWT、数据库密码等敏感信息。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO

# 后端根目录：本文件位于 backend/app/logging_setup.py，parents[1] 即 backend/。
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_LOG_DIR = _BACKEND_DIR / "logs"

# reload 会重复导入本模块；用模块级标记避免重复安装 Tee 与 handler。
_installed_path: Path | None = None


class _Tee:
    """把写入同时转发到原始流与日志文件，保持 UTF-8 且即时 flush 便于崩溃排查。"""

    def __init__(self, stream: TextIO, file_handle: TextIO) -> None:
        self._stream = stream
        self._file = file_handle

    def write(self, data: str) -> int:
        self._stream.write(data)
        self._file.write(data)
        self._file.flush()
        return len(data)

    def flush(self) -> None:
        self._stream.flush()
        self._file.flush()

    def __getattr__(self, name: str):
        # isatty/fileno/encoding 等一律委托给原始流，保证第三方库探测行为不变。
        return getattr(self._stream, name)


def setup_file_logging(log_dir: Path | str | None = None) -> Path:
    """安装日志持久化；返回当前日志文件路径。重复调用是幂等的。"""
    global _installed_path
    if _installed_path is not None:
        return _installed_path

    directory = Path(log_dir) if log_dir is not None else _DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / f"backend-{datetime.now():%Y%m%d}.log"

    # 单一共享句柄：Tee 与 logging handler 都写它，避免多句柄交错与 Windows 文件锁。
    handle = open(log_path, "a", encoding="utf-8", errors="replace")
    handle.write(f"\n{'=' * 60}\n启动日志会话: {datetime.now():%Y-%m-%d %H:%M:%S}\n{'=' * 60}\n")
    handle.flush()

    # 保存原始流：logging 的控制台 handler 必须写原始 stdout。
    # 若写 Tee 包装后的 sys.stdout，每条日志会经 Tee 再次落盘造成重复。
    original_stdout = sys.stdout
    sys.stdout = _Tee(sys.stdout, handle)  # type: ignore[assignment]
    sys.stderr = _Tee(sys.stderr, handle)  # type: ignore[assignment]

    # uvicorn 的 access/error handler 在导入 app 之前已绑定原始 stderr，Tee 抓不到；
    # 这里把共享句柄挂到 uvicorn logger（propagate=False）上补齐落盘，控制台输出不受影响。
    file_handler = logging.StreamHandler(handle)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    file_handler.setLevel(logging.INFO)
    for logger_name in ("uvicorn", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        if not any(getattr(h, "_trip_planner_file", False) for h in logger.handlers):
            file_handler._trip_planner_file = True  # type: ignore[attr-defined]
            logger.addHandler(file_handler)

    # 应用代码（app.services.* 等）已从 print 迁移到 logging；给 root logger 挂
    # 控制台 + 共享文件双 handler，保证 INFO 及以上日志既可见又落盘。
    root = logging.getLogger()
    if not any(getattr(h, "_trip_planner_root", False) for h in root.handlers):
        console_handler = logging.StreamHandler(original_stdout)
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        console_handler.setLevel(logging.INFO)
        console_handler._trip_planner_root = True  # type: ignore[attr-defined]
        root.addHandler(console_handler)

        root_file_handler = logging.StreamHandler(handle)
        root_file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root_file_handler.setLevel(logging.INFO)
        root_file_handler._trip_planner_root = True  # type: ignore[attr-defined]
        root.addHandler(root_file_handler)
        root.setLevel(logging.INFO)

    _installed_path = log_path
    return log_path
