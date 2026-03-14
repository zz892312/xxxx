FROM python:3.12-slim

WORKDIR /app

# Install oc CLI
RUN apt-get update && apt-get install -y curl tar && \
    curl -sL https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz \
    | tar -xz -C /usr/local/bin oc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Run as non-root
RUN useradd -m broker
USER broker

EXPOSE 8080
CMD ["python", "main.py"]
