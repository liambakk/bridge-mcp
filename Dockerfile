# The Bridge participants MCP server — container image for Fly.io.
FROM python:3.13-slim

WORKDIR /app

# Install the package first (cached unless project metadata/source changes).
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Bake the participant data export into the image. Gated at runtime by OAuth.
COPY founders.json ./founders.json

ENV BRIDGE_DATA_FILE=/app/founders.json \
    HOST=0.0.0.0 \
    PORT=8080

EXPOSE 8080

# AUTHKIT_DOMAIN and BRIDGE_PUBLIC_URL are provided as Fly secrets at runtime,
# which switches the server into OAuth mode for hosted chatbot connectors.
CMD ["bridge-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
