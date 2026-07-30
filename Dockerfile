# Use Python 3.11 + Node.js 20 base image
FROM nikolaik/python-nodejs:python3.11-nodejs20-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Node.js frontend dependencies and install
COPY demo-ui/package*.json ./demo-ui/
RUN cd demo-ui && npm install --production

# Copy all application source files
COPY . .

# Set environment variables
ENV PORT=3000
ENV PYTHONUNBUFFERED=1

EXPOSE 3000

# Start application server
CMD ["node", "demo-ui/server.js"]
