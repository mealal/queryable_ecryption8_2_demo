FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including curl and tar for downloading crypt_shared
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Download and install MongoDB crypt_shared library for automatic encryption
# Using MongoDB 8.2.1 crypt_shared to support substringPreview query type
RUN mkdir -p /usr/local/lib/mongo_crypt && \
    cd /tmp && \
    curl -L https://downloads.mongodb.com/linux/mongo_crypt_shared_v1-linux-x86_64-enterprise-ubuntu2204-8.2.1.tgz -o crypt_shared.tgz && \
    tar -xzf crypt_shared.tgz && \
    cp -r lib/* /usr/local/lib/mongo_crypt/ && \
    echo "/usr/local/lib/mongo_crypt" > /etc/ld.so.conf.d/mongo_crypt.conf && \
    ldconfig && \
    rm -rf /tmp/crypt_shared.tgz /tmp/lib

# Copy API code
COPY api/ /app/api/

# Expose API port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV LD_LIBRARY_PATH=/usr/local/lib/mongo_crypt:$LD_LIBRARY_PATH

# Start API server
CMD ["python", "api/app.py"]
