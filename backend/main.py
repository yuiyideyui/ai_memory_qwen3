# main.py
import socketio
import uvicorn
# 导入 app.py 中创建的 Socket.IO ASGI 应用
# 假设 app.py 中将最终的 ASGI 应用命名为 sio_app
try:
    from app import sio_app
except ImportError:
    # 如果 app.py 没有导出 sio_app，使用 app 和 sio 重新创建它
    # 这是一种后备方案，但最好确保 app.py 只负责创建一次
    from app import app, sio
    sio_app = socketio.ASGIApp(sio, app)


if __name__ == "__main__":
    # 直接运行包含 FastAPI 和 Socket.IO 的 sio_app
    uvicorn.run(sio_app, host="127.0.0.1", port=8000, log_level="info")