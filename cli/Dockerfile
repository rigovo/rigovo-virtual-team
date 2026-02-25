FROM python:3.12-slim

WORKDIR /app

# Install system deps for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 (for Rigour CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY src/ src/
COPY tests/ tests/
COPY rigour.yml ./

# Install dependencies
RUN uv pip install --system -e ".[dev]"

# Install build tools
RUN uv pip install --system build twine python-semantic-release

ENTRYPOINT ["rigovo"]
CMD ["--help"]
