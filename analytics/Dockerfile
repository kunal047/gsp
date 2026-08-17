FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first so ultralytics/easyocr don't pull the huge CUDA build.
RUN pip install --no-cache-dir torch==2.2.2 torchvision==0.17.2 \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake model weights into the image so there is no runtime download
# (robust even if the venue network blocks model hosts).
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
RUN python -c "import easyocr; easyocr.Reader(['en'], gpu=False)"
# Dedicated YOLO license-plate detector (morsetechlab/yolov11-license-plate).
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://huggingface.co/morsetechlab/yolov11-license-plate-detection/resolve/main/license-plate-finetune-v1n.pt', '/app/plate.pt')"
RUN python -c "from ultralytics import YOLO; YOLO('/app/plate.pt')"

COPY . .

CMD ["python", "worker.py"]
