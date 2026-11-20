FROM eclipse-temurin:25-jdk-noble AS studio-jdk
FROM ubuntu:24.04 AS audiveris-base
ARG DEBIAN_FRONTEND=noninteractive
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl python3-venv xvfb xauth fonts-dejavu libasound2t64 libxi6 libxrender1 libxtst6 libxext6 libgl1 tesseract-ocr-eng tesseract-ocr-chi-tra tesseract-ocr-chi-sim \
 && curl -fL --retry 3 https://github.com/Audiveris/audiveris/releases/download/5.11.0/Audiveris-5.11.0-ubuntu24.04-x86_64.deb -o /tmp/audiveris.deb \
 && echo "f20113aaa33b3149ec8d6a09b2a7963360e65fafd92d69389987a85bbc3ec7a3  /tmp/audiveris.deb" | sha256sum -c - \
 && dpkg-deb -x /tmp/audiveris.deb / && test -x /opt/audiveris/bin/Audiveris && rm -f /tmp/audiveris.deb && rm -rf /var/lib/apt/lists/*
FROM audiveris-base AS studio-engine
COPY --from=studio-jdk /opt/java/openjdk /opt/compiler
RUN apt-get update && apt-get install -y --no-install-recommends git
COPY engine /tmp/engine
RUN python3 /tmp/engine/build_patch.py /opt/audiveris/lib/app --jdk-bin /opt/compiler/bin

FROM audiveris-base
COPY --from=studio-engine /opt/audiveris/lib/app/audiveris.jar /opt/audiveris/lib/app/audiveris.jar
ENV PATH=/opt/studio/bin:$PATH AUDIVERIS_CMD=/usr/local/bin/studio-scanner TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
# The desktop distribution reserves a 512 MB initial heap and allows 8 GB.
# Size the hosted launcher relative to its container and leave room for Studio.
RUN sed -i -e 's/^-*java-options=-Xms512m$/java-options=-Xms24m/' -e 's/^java-options=-Xmx8G$/java-options=-XX:MaxRAMPercentage=32/' /opt/audiveris/lib/app/Audiveris.cfg
COPY requirements-studio.txt .
RUN python3 -m venv /opt/studio && pip install --no-cache-dir -r requirements-studio.txt 'psycopg[binary]>=3.2,<4'
COPY src ./src
RUN printf '%s\n' '#!/bin/sh' 'exec xvfb-run -a /opt/audiveris/bin/Audiveris "$@"' > /usr/local/bin/studio-scanner && chmod 755 /usr/local/bin/studio-scanner
USER ubuntu
CMD ["python", "-u", "-m", "src.studio.server", "--no-browser", "--data-dir", "/tmp/solfa"]
