"""Concise terminal output shared by direct unittest scripts."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import time
import unittest


def run_unittest(description: str) -> None:
    """Run the current script's suite with concise Chinese terminal output."""
    module = sys.modules["__main__"]
    name = Path(str(getattr(module, "__file__", "test"))).stem
    print(f"【单元测试】{name}")
    print(f"说明：{description}")
    started = time.perf_counter()
    captured = StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    with redirect_stdout(captured), redirect_stderr(captured):
        result = unittest.TextTestRunner(stream=captured, verbosity=0).run(suite)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if result.wasSuccessful():
        print(f"结果：通过 {result.testsRun} 项，耗时 {elapsed_ms} ms")
        return

    print(
        f"结果：失败 {len(result.failures) + len(result.errors)} 项，"
        f"耗时 {elapsed_ms} ms"
    )
    print(captured.getvalue().strip())
    raise SystemExit(1)
