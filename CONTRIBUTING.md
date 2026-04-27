# Contributing to JARVIS

Thanks for considering a contribution! Here's how to get going.

## 🛠️ Development setup

```bash
git clone https://github.com/<your-username>/jarvis.git
cd jarvis
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # add your Groq key
```

## 🧩 Adding a new tool

JARVIS uses [Model Context Protocol](https://modelcontextprotocol.io). Adding a tool is three steps:

### 1. Implement it

```python
# backend/tools/my_tool.py
async def do_something(query: str) -> dict:
    return {"result": f"You asked: {query}"}
```

### 2. Register with MCP

```python
# mcp_server/server.py
from backend.tools import my_tool

@mcp.tool()
async def do_something(query: str) -> dict:
    """Describe what your tool does. The LLM reads this docstring to decide
    when to call it — be specific about the trigger phrases."""
    return await my_tool.do_something(query)
```

### 3. (Optional) Add a HUD handler

If your tool produces visual output, add a UI event in `backend/jarvis_agent.py`:

```python
def _build_ui_event(tool_name, tool_args, result):
    if tool_name == "do_something":
        return {"type": "show_my_panel", "data": result}
```

…and a frontend handler in `frontend/index.html`:

```javascript
case 'show_my_panel': showMyPanel(ev); break;
```

Restart MCP — JARVIS auto-discovers the new tool.

## 🐛 Reporting bugs

Open an issue with:

- The actual logs (FastAPI + MCP server)
- Browser console output
- Steps to reproduce
- Your `.env` (with **keys redacted!**)

## 📐 Code style

- Type hints where they help
- Async I/O end-to-end (no blocking calls inside async paths)
- Tool results should be JSON-serialisable
- Keep tool docstrings detailed — they're the LLM's only spec

## 🚦 Pull request checklist

- [ ] Code runs with `start.bat` / `start.sh`
- [ ] No real API keys committed
- [ ] New tools have docstrings with trigger phrases
- [ ] README updated if user-facing behaviour changed

Cheers!
