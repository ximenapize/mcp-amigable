# amigable-mef como servidor remoto (HTTP en el puerto $PORT, ruta /mcp).
#   docker build -t amigable-mef .
#   docker run -p 8000:8000 -e AMIGABLE_TOKEN=una-clave amigable-mef
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY server.py glosario.csv ./

# La caché va a /tmp: se pierde al reiniciar, pero se vuelve a llenar sola
ENV MCP_TRANSPORT=http PORT=8000 AMIGABLE_CACHE=/tmp/amigable-cache
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-dev", "server.py"]
