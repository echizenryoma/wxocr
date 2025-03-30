FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY . /app

WORKDIR /app

RUN uv sync

ENTRYPOINT [ "uv", "run", "wechat-ocr" ]
