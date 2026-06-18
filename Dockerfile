FROM public.ecr.aws/lambda/python:3.11

# Install system dependencies required for OCR (Tesseract) and general image handling
RUN yum install -y \
    wget \
    tar \
    gzip \
    libgl1 \
    libglib2.0-0 \
    gcc \
    gcc-c++ \
    make \
    && yum clean all

# Install pandoc (if you actually need it)
RUN wget https://github.com/jgm/pandoc/releases/download/3.1.9/pandoc-3.1.9-linux-amd64.tar.gz -O /tmp/pandoc.tar.gz && \
    tar -xzf /tmp/pandoc.tar.gz -C /tmp && \
    mv /tmp/pandoc-3.1.9/bin/pandoc /usr/local/bin/pandoc && \
    chmod +x /usr/local/bin/pandoc && \
    rm -rf /tmp/pandoc*

# Copy requirements first (better layer caching)
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN python3.11 -m pip install --upgrade pip && \
    python3.11 -m pip install -r requirements.txt

# Copy application code
COPY app ${LAMBDA_TASK_ROOT}/app

# Set Lambda handler
CMD ["app.main.handler"]