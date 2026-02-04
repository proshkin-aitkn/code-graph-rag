# Mac Installation Guide for Graph-Code

A step-by-step guide to install and configure Graph-Code on macOS, including MCP integration with Claude Code.

## Prerequisites

### 1. Install Homebrew (if not already installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Install Required Tools

```bash
# Required dependencies
brew install cmake ripgrep python@3.12 uv

# Docker Desktop (for Memgraph)
brew install --cask docker
```

### 3. Start Docker Desktop

Open Docker Desktop from Applications and wait for it to start.

## Installation

### 1. Clone the Repository

```bash
cd ~/projects  # or your preferred directory
git clone https://github.com/vitali87/code-graph-rag.git
cd code-graph-rag
```

### 2. Install Python Dependencies

```bash
# Full installation with all language support
uv sync --extra treesitter-full

# Or minimal (Python only)
uv sync
```

### 3. Start Memgraph Database

Create a `docker-compose.yaml` with custom ports (to avoid conflicts):

```yaml
services:
  memgraph:
    image: memgraph/memgraph-mage
    ports:
      - "17687:7687"    # Bolt protocol
      - "17444:7444"    # HTTP API
  lab:
    image: memgraph/lab
    ports:
      - "3001:3000"     # Web UI
    environment:
      QUICK_CONNECT_MG_HOST: memgraph
```

Start the services:

```bash
docker compose up -d
```

Verify Memgraph is running:

```bash
docker ps
# Should show memgraph and lab containers
```

Access Memgraph Lab at: http://localhost:3001

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your preferred settings:

```bash
# Memgraph settings (match docker-compose ports)
MEMGRAPH_HOST=localhost
MEMGRAPH_PORT=17687
MEMGRAPH_HTTP_PORT=17444
LAB_PORT=3001
MEMGRAPH_BATCH_SIZE=1000

# Repository to analyze
TARGET_REPO_PATH=.
```

## LLM Provider Configuration

Choose ONE of the following options in your `.env`:

### Option A: Google Gemini (Recommended for beginners)

Get your API key from [Google AI Studio](https://aistudio.google.com/app/apikey)

```bash
ORCHESTRATOR_PROVIDER=google
ORCHESTRATOR_MODEL=gemini-2.5-pro
ORCHESTRATOR_API_KEY=your-google-api-key

CYPHER_PROVIDER=google
CYPHER_MODEL=gemini-2.5-flash
CYPHER_API_KEY=your-google-api-key
```

### Option B: OpenAI

```bash
ORCHESTRATOR_PROVIDER=openai
ORCHESTRATOR_MODEL=gpt-4o
ORCHESTRATOR_API_KEY=sk-your-openai-key

CYPHER_PROVIDER=openai
CYPHER_MODEL=gpt-4o-mini
CYPHER_API_KEY=sk-your-openai-key
```

### Option C: Anthropic Claude (Direct API)

```bash
ORCHESTRATOR_PROVIDER=anthropic
ORCHESTRATOR_MODEL=claude-sonnet-4-5-20250929
ORCHESTRATOR_API_KEY=sk-ant-your-key

CYPHER_PROVIDER=anthropic
CYPHER_MODEL=claude-haiku-4-20250514
CYPHER_API_KEY=sk-ant-your-key
```

### Option D: Claude Max Subscription (via CLI Wrapper)

If you have a Claude Max subscription, you can use it without an API key:

```bash
# In .env
ORCHESTRATOR_PROVIDER=openai
ORCHESTRATOR_MODEL=claude-opus-4-5-20251101
ORCHESTRATOR_ENDPOINT=http://localhost:8000/v1
ORCHESTRATOR_API_KEY=dummy

CYPHER_PROVIDER=openai
CYPHER_MODEL=claude-sonnet-4-5-20250929
CYPHER_ENDPOINT=http://localhost:8000/v1
CYPHER_API_KEY=dummy
```

Start the wrapper before using Graph-Code:

```bash
# In a separate terminal
uv run python claude_api_wrapper.py
```

### Option E: Ollama (Free, Local)

Install Ollama first: https://ollama.ai

```bash
# Pull models
ollama pull llama3.2
ollama pull codellama

# In .env
ORCHESTRATOR_PROVIDER=ollama
ORCHESTRATOR_MODEL=llama3.2
ORCHESTRATOR_ENDPOINT=http://localhost:11434/v1

CYPHER_PROVIDER=ollama
CYPHER_MODEL=codellama
CYPHER_ENDPOINT=http://localhost:11434/v1
```

## Optional: Semantic Search with Qdrant

For semantic code search (find functions by description), install Qdrant:

```bash
# Run Qdrant server
docker run -d -p 6333:6333 -p 6334:6334 \
  -v ~/qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

Add to `.env`:

```bash
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

Without Qdrant, Graph-Code uses local file storage (single-process only).

## Usage

### CLI Mode

```bash
# Index a repository
uv run graph-code start --repo-path /path/to/your/project --update-graph --clean

# Start interactive chat
uv run graph-code start --repo-path /path/to/your/project
```

### MCP Integration with Claude Code

Add Graph-Code as an MCP server to Claude Code:

```bash
# Navigate to your project
cd /path/to/your/project

# Add MCP server (using Google Gemini for Cypher generation)
claude mcp add --transport stdio graph-code \
  --env TARGET_REPO_PATH="$(pwd)" \
  --env MEMGRAPH_HOST=localhost \
  --env MEMGRAPH_PORT=17687 \
  --env CYPHER_PROVIDER=google \
  --env CYPHER_MODEL=gemini-2.5-flash \
  --env CYPHER_API_KEY=your-google-api-key \
  -- uv run --directory ~/projects/code-graph-rag graph-code mcp-server
```

Replace:
- `~/projects/code-graph-rag` with where you cloned this repo
- `your-google-api-key` with your actual API key

#### Available MCP Tools

| Tool | Description |
|------|-------------|
| `index_repository` | Build knowledge graph from codebase |
| `update_repository` | Update graph without clearing |
| `query_code_graph` | Natural language queries |
| `get_code_snippet` | Get source code by qualified name |
| `semantic_search` | Find code by description |
| `surgical_replace_code` | Precise code edits |
| `read_file` / `write_file` | File operations |
| `list_directory` | Browse directories |

#### Example Queries

```
> Index this repository
> What functions call the UserService class?
> Show me all authentication-related code
> Find functions that handle errors
> How does the payment flow work?
```

## Verify Installation

```bash
# Check Memgraph connection
uv run python -c "
from codebase_rag.services.graph_service import MemgraphIngestor
ing = MemgraphIngestor(host='localhost', port=17687)
with ing:
    print('Connected to Memgraph successfully!')
"

# Check CLI works
uv run graph-code --help
```

## Troubleshooting

### Memgraph Connection Failed

```bash
# Check if containers are running
docker ps

# Restart containers
docker compose down
docker compose up -d

# Check logs
docker compose logs memgraph
```

### pymgclient Build Fails

```bash
# Ensure cmake is installed
brew install cmake

# Reinstall
uv sync --reinstall
```

### MCP Tools Not Showing

```bash
# Verify MCP configuration
claude mcp list

# Remove and re-add if needed
claude mcp remove graph-code
# Then add again with correct paths
```

### Port Conflicts

If ports are in use, change them in `docker-compose.yaml` and `.env`:

```yaml
# docker-compose.yaml
ports:
  - "27687:7687"  # Different port
```

```bash
# .env
MEMGRAPH_PORT=27687
```

## Updating

```bash
cd ~/projects/code-graph-rag
git pull
uv sync --extra treesitter-full
```

## Uninstalling

```bash
# Stop and remove containers
docker compose down -v

# Remove MCP server
claude mcp remove graph-code

# Remove directory
rm -rf ~/projects/code-graph-rag
```
