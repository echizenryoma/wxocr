import os
import uuid
import base64
import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from loguru import logger

from . import wcocr  # 你的 wcocr 扩展模块

# ------------------ 配置日志 ------------------
# 创建日志目录
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

TOKEN = os.getenv("TOKEN", "mysecrettoken")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5001"))

# 配置日志输出
logger.remove()  # 移除默认的处理器
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    log_dir / "app_{time}.log",
    rotation="500 MB",
    retention="10 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG"
)

# ------------------ 初始化 FastAPI ------------------
app = FastAPI(
    title="OCR Service",
    description="OCR 服务，需要携带 Token 认证",
    version="1.0.0",
)

# ------------------ 初始化 wcocr ------------------
# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 构建完整路径
WXOCR_PATH = os.path.join(BASE_DIR, "wechat/wxocr")
WECHAT_PATH = os.path.join(BASE_DIR, "wechat")

# 初始化 wcocr
logger.info("Initializing wcocr with paths: WXOCR_PATH={}, WECHAT_PATH={}", WXOCR_PATH, WECHAT_PATH)
wcocr.init(WXOCR_PATH, WECHAT_PATH)
logger.info("wcocr initialized successfully")

# ------------------ 定义安全校验 ------------------
security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.scheme.lower() != "bearer":
        logger.warning("Invalid authentication scheme: {}", credentials.scheme)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme",
        )
    # 简单固定值校验，可根据实际需要改成更复杂的验证逻辑
    if credentials.credentials != TOKEN:
        logger.warning("Invalid token provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    logger.debug("Token verified successfully")
    return credentials.credentials


# ------------------ 请求体模型定义 ------------------
class OCRRequest(BaseModel):
    image: str  # Base64 编码的图像数据，可能带前缀 data:image/png;base64,...


# ------------------ 去除 Base64 前缀的函数 ------------------
def remove_base64_prefix(data: str) -> str:
    """
    如果 Base64 字符串开头有类似 data:image/png;base64, 或 data:image/jpeg;base64, 的前缀，
    则去除该前缀并返回真正的 Base64 内容。
    """
    if data.startswith("data:image"):
        comma_index = data.find(",")
        if comma_index != -1:
            return data[comma_index + 1 :]
    return data


# ------------------ 帮助函数: 根据文件头猜测图片后缀 ------------------
def guess_image_extension(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    elif data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    elif data.startswith(b"BM"):
        return "bmp"
    else:
        return "png"  # 默认给个 png


# ------------------ OCR 接口 ------------------
@app.post("/ocr", tags=["OCR"])
def ocr_api(request_data: OCRRequest, token: str = Depends(verify_token)):
    """
    接口说明:
    - 请求体中必须有 image 字段，对应 base64 编码的图像数据(可能含 data:image/*;base64, 前缀)
    - 请求头中必须携带: Authorization: Bearer mysecrettoken
    """
    try:
        logger.info("Received OCR request")
        # 去除可能的 base64 前缀
        base64_str = remove_base64_prefix(request_data.image)
        if not base64_str:
            logger.error("No image data provided in request")
            raise HTTPException(status_code=400, detail="No image data provided")

        # 解码 base64
        try:
            image_bytes = base64.b64decode(base64_str)
            logger.debug("Successfully decoded base64 image data, size: {} bytes", len(image_bytes))
        except Exception as e:
            logger.error("Failed to decode base64 image data: {}", str(e))
            raise HTTPException(status_code=400, detail="Invalid base64 image data")

        # 创建临时目录
        temp_dir = "temp"
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
            logger.debug("Created temporary directory: {}", temp_dir)

        # 根据内容猜测后缀
        ext = guess_image_extension(image_bytes)
        filename = os.path.join(temp_dir, f"{uuid.uuid4()}.{ext}")
        logger.debug("Generated temporary filename: {}", filename)

        # 保存文件
        with open(filename, "wb") as f:
            f.write(image_bytes)
        logger.debug("Saved image to temporary file")

        try:
            # 调用 OCR
            logger.info("Starting OCR processing")
            result = wcocr.ocr(filename)
            logger.info("OCR processing completed successfully")
            return {"result": result}
        finally:
            # 删除临时文件
            if os.path.exists(filename):
                os.remove(filename)
                logger.debug("Removed temporary file: {}", filename)

    except HTTPException as e:
        logger.error("HTTP error occurred: {}", str(e))
        raise e
    except Exception as e:
        logger.exception("Unexpected error occurred during OCR processing")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------ 入口 (可选) ------------------
def main():
    import cpuinfo

    info = cpuinfo.get_cpu_info()
    if "avx2" not in info["flags"]:
        logger.error("AVX2 is not supported on this system")
        sys.exit(1)
    
    logger.info("Starting OCR service on {}:{}", HOST, PORT)
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
