FROM python:3.11-slim-bookworm

# Install system dependencies required for libvirt-python and other tools
RUN apt-get update && apt-get install -y \
    pkg-config \
    libvirt-dev \
    gcc \
    libvirt-clients \
    genisoimage \
    qemu-utils \
    p7zip-full \
    nmap \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install NoVNC
RUN git clone https://github.com/novnc/noVNC.git /opt/novnc \
    && git clone https://github.com/novnc/websockify /opt/novnc/utils/websockify \
    && ln -s /opt/novnc/vnc.html /opt/novnc/index.html

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose API port and VNC range
EXPOSE 8001
EXPOSE 6080-6100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
