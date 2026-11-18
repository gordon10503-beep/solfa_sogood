FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl python3-venv xvfb xauth fonts-dejavu tesseract-ocr-eng tesseract-ocr-chi-tra tesseract-ocr-chi-sim \
 && curl -fL --retry 3 https://github.com/Audiveris/audiveris/releases/download/5.11.0/Audiveris-5.11.0-ubuntu24.04-x86_64.deb -o /tmp/audiveris.deb \
 && echo "f20113aaa33b3149ec8d6a09b2a7963360e65fafd92d69389987a85bbc3ec7a3  /tmp/audiveris.deb" | sha256sum -c - \
 && apt-get install -y --no-install-recommends /tmp/audiveris.deb \
 && launcher="$(dpkg -L "$(dpkg-deb -f /tmp/audiveris.deb Package)" | grep -i '/bin/audiveris$' | head -1)" && test -x "$launcher" \
 && ln -s "$launcher" /usr/local/bin/studio-scanner && rm -f /tmp/audiveris.deb && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/studio/bin:$PATH AUDIVERIS_CMD=/usr/local/bin/studio-scanner TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
COPY requirements-studio.txt .
RUN python3 -m venv /opt/studio && pip install --no-cache-dir -r requirements-studio.txt 'psycopg[binary]>=3.2,<4'
COPY src ./src
USER ubuntu
CMD ["xvfb-run", "-a", "python", "-m", "src.studio.server", "--no-browser", "--data-dir", "/tmp/solfa"]
