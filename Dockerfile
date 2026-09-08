FROM python:3.11-slim
 
# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    tar \
    gzip \
    libgl1 \
    libglib2.0-0 \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*
 
# Install pandoc
RUN wget https://github.com/jgm/pandoc/releases/download/3.1.9/pandoc-3.1.9-linux-amd64.tar.gz -O /tmp/pandoc.tar.gz && \
    tar -xzf /tmp/pandoc.tar.gz -C /tmp && \
    mv /tmp/pandoc-3.1.9/bin/pandoc /usr/local/bin/pandoc && \
    chmod +x /usr/local/bin/pandoc && \
    rm -rf /tmp/pandoc*
 
WORKDIR /app
 
# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
 
# Copy application code
COPY app ./app

# The filed returns the benchmark scores against, and which supply the
# organization's identity and subsection. Without them the benchmark finds no
# reference documents and organizationInformation comes back empty -- the
# image previously shipped with app/ alone.
COPY docs ./docs

EXPOSE 8000
 
# Run with uvicorn (ECS long-running process)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]