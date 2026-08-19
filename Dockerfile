FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        librtlsdr2 \
        libhackrf0 \
        libportaudio2 \
        libqt6core6t64 \
        libqt6gui6t64 \
        libqt6widgets6t64 \
        libqt6network6t64 \
        libqt6svg6 \
        libqt6opengl6t64 \
        libqt6printsupport6t64 \
        libqt6dbus6t64 \
        libqt6core5compat6 \
        qt6-qpa-plugins \
        libxcb-cursor0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
        libxcb-render-util0 \
        libxcb-shape0 \
        libxcb-xinerama0 \
        libxcb-xkb1 \
        libxkbcommon-x11-0 \
        libgl1 \
        libegl1 \
        desktop-file-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY scripts/patch_rtlsdr.py /tmp/patch_rtlsdr.py
RUN python3 /tmp/patch_rtlsdr.py && rm /tmp/patch_rtlsdr.py

COPY . .

CMD ["python3", "main.py"]
