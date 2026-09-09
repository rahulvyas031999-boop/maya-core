FROM python:3.10-slim

# बफ़र बंद करें ताकि लाइव डिबग लॉग्स तुरंत कंसोल में दिखें
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# नॉन-रूट यूज़र और डायरेक्टरी परमिशन सेटअप
RUN useradd -m appuser && \
    mkdir -p /app/workspace && \
    chown -R appuser:appuser /app

USER appuser

# Persistence variables (maya_tasks.db के साथ सिंक किया गया)
ENV DB_PATH=maya_tasks.db \
    STATE_FILE_PATH=maya_state.json \
    WORKSPACE_PATH=workspace

EXPOSE 10000

# Healthcheck में IPv6 ट्रैप से बचने के लिए 127.0.0.1 का उपयोग
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10000/health')" || exit 1

# रिवर्स प्रॉक्सी और वेबसॉकेट स्थिरता के लिए प्रॉक्सी हेडर्स शामिल किए गए
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000", "--proxy-headers", "--forwarded-allow-ips", "*"]
