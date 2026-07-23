cd test

## 安装测试依赖

请使用运行测试脚本的同一个 Python 环境安装：

```powershell
python -m pip install -r requirements.txt
python -m playwright install
```

脚本使用本机 Microsoft Edge，通常不需要额外下载 Edge 浏览器；`playwright install` 用于补齐 Playwright 运行依赖。

## test_api.py

## test_trip_planner.py

运行前请保持两个服务处于启动状态：

```powershell
# 终端 1：后端
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2：前端
cd frontend
npm run dev -- --host 0.0.0.0

# 终端 3：测试
cd test
```

python test_trip_planner.py
