# 🏗️ JARVIS — System Architecture

A deep dive into the internals. Three diagrams: **components**, **request flow**, and the **tool ecosystem**.

---

## 1. Component overview

```mermaid
graph TB
    subgraph Browser["🖥️  BROWSER  (frontend/index.html)"]
        UI[HUD UI<br/>windows · panels · charts]
        MIC[🎤 Mic recorder<br/>WebM/Opus]
        DROP[📁 Drop zone<br/>files + images]
        CAM[📷 Webcam capture]
        SCR[🖥️ Screen capture]
        SIO_C[Socket.IO client]
        TTS_OUT[🔊 Audio playback]
    end

    subgraph FastAPI["⚡ FASTAPI SERVER  :8000  (backend/server.py)"]
        REST[REST endpoints<br/>/api/status · /api/world/*]
        SIO_S[Socket.IO server]
        AGENT[JarvisAgent<br/>per-session]
    end

    subgraph Pipeline["🧠 AGENT PIPELINE  (backend/jarvis_agent.py)"]
        STT[STT<br/>Groq Whisper-large-v3]
        LLM[LLMClient<br/>multi-provider failover]
        TTS[TTS<br/>Edge-TTS]
        RESCUE[Tool-call rescue<br/>+ slim results]
    end

    subgraph LLMProviders["🌐 LLM PROVIDERS  (backend/llm.py)"]
        GROQ[Groq<br/>gpt-oss-120b → llama-3.3-70b]
        CEREB[Cerebras]
        OR[OpenRouter]
        GEM[Gemini]
        VIS[Vision LLM<br/>llama-4-scout · gemini-2.5]
    end

    subgraph MCP["🛠️ MCP TOOLS SERVER  :8001  (mcp_server/server.py)"]
        TOOLS[35+ tools]
    end

    subgraph Storage["💾 PERSISTENT STORAGE"]
        SQLITE[(SQLite<br/>jarvis_memory.db)]
        TEMP[(Temp uploads<br/>%TEMP%/jarvis_uploads/)]
    end

    MIC -->|audio_upload| SIO_C
    DROP -->|file_upload| SIO_C
    CAM --> SIO_C
    SCR --> SIO_C
    UI -->|text_in| SIO_C
    SIO_C <==>|WebSocket| SIO_S
    SIO_S --> AGENT
    AGENT --> STT
    STT --> LLM
    LLM <--> RESCUE
    LLM --> TTS
    TTS -->|audio_out| SIO_S
    SIO_S -->|response_text<br/>ui_event| SIO_C
    SIO_C --> UI
    SIO_C --> TTS_OUT

    LLM -.failover.-> GROQ
    LLM -.failover.-> CEREB
    LLM -.failover.-> OR
    LLM -.failover.-> GEM
    AGENT -.vision.-> VIS

    AGENT <-->|SSE| MCP
    MCP --> SQLITE
    AGENT --> TEMP
    MCP --> TEMP

    style Browser fill:#0a1828,stroke:#00d4ff,color:#fff
    style FastAPI fill:#0a1828,stroke:#00d4ff,color:#fff
    style Pipeline fill:#0a1828,stroke:#ff6600,color:#fff
    style LLMProviders fill:#0a1828,stroke:#00ff99,color:#fff
    style MCP fill:#0a1828,stroke:#cc66ff,color:#fff
    style Storage fill:#0a1828,stroke:#ffcc00,color:#fff
```

---

## 2. Single-turn request flow

```mermaid
sequenceDiagram
    actor User
    participant Browser
    participant FastAPI as FastAPI<br/>:8000
    participant Agent as JarvisAgent
    participant STT as Groq Whisper
    participant LLM as LLM Cascade
    participant MCP as MCP Server<br/>:8001
    participant TTS as Edge TTS
    participant SQLite

    User->>Browser: 🎤 "JARVIS, analyse my CSV"
    Browser->>FastAPI: audio_upload (WebM bytes)
    FastAPI->>Agent: send_audio()
    Agent->>STT: transcribe(bytes)
    STT-->>Agent: "JARVIS, analyse my CSV"
    Agent->>Browser: transcript event
    Agent->>SQLite: log_turn(user, text)
    Agent->>SQLite: load top 12 memories
    Agent->>LLM: generate(messages, tools, system+memories)

    Note over LLM: Try gpt-oss-120b<br/>(skip cooldowned models)
    LLM-->>Agent: tool_calls=[analyze_file{sid}]

    Agent->>Agent: rescue malformed<br/>function calls in text
    Agent->>MCP: call_tool('analyze_file', {sid})
    MCP->>MCP: _resolve_file → disk scan
    MCP-->>Agent: {summary, plotly_spec, ui_command}
    Agent->>Browser: ui_event: show_chart
    Agent->>Agent: slim result (98KB→235B)<br/>before LLM round 2

    Agent->>LLM: generate(messages+tool_result)
    LLM-->>Agent: "Analysis complete, sir..."
    Agent->>SQLite: log_turn(assistant, text)

    Agent->>Browser: response_text
    Agent->>TTS: synthesize(text)
    TTS-->>Agent: MP3 bytes
    Agent->>Browser: audio_out (b64 MP3)
    Browser->>User: 🔊 spoken reply<br/>📈 chart window
```

---

## 3. Tool ecosystem (35+ tools)

```mermaid
mindmap
  root((JARVIS<br/>Tools))
    🌐 News & Web
      search_web
      get_world_news
      get_finance_news
      get_tech_news
      wiki_search
    👁️ Vision
      describe_image
      read_text_from_image
      detect_objects_in_image
      analyze_chart_image
      capture_screen
    🧠 Memory
      remember
      recall
      forget_memory
      list_memories
      memory_stats
      search_history
    📊 Analytics
      analyze_file
      plot_chart
      plot_3d_chart
      plot_neural_network
      get_data_summary
    🪟 Windows / HUD
      open_world_map
      open_globe
      open_news_wire
      open_crypto_market
      open_stocks
      open_weather
      close_all_windows
    📺 YouTube
      youtube_search
      play_youtube
    ⚙️ System
      get_current_time
      run_diagnostics
      get_weather
    🌍 World Monitor
      world_population
      world_covid
```

---

## 4. Key engineering decisions

### Why FastMCP + SSE?

The Model Context Protocol gives us tool definitions, schemas, and call routing for free. SSE lets the agent stream tool catalogue updates without re-establishing a connection. The MCP server runs in its own process so a tool crash can't take down the FastAPI server.

### Why an in-memory + on-disk file store?

The FastAPI process and the MCP process are separate. A pure in-memory dict only solves half the problem — uploads happened in process A but tools resolve files in process B. The disk fallback (with three-tier resolution) makes the cross-process boundary invisible to the LLM.

### Why slim tool results before round 2?

Plotly chart specs are ~98 KB. Sending that back to the LLM as a tool result would burn through Groq's per-minute token cap (6,000 TPM) on a single call. The slim pass strips heavy fields, keeps the LLM-relevant summary, and reduces token usage by 87–99%.

### Why per-model cooldowns?

When Groq's `llama-3.3-70b-versatile` hits its daily cap, the error message helpfully says `"try again in 51m45s"`. Without a cooldown registry, every subsequent request burns 1–2 seconds retrying that dead model before falling through. With cooldowns, dead models are skipped instantly until their `ready_at` timestamp passes.

### Why two-step tool-call rescue?

Groq's Llama models occasionally emit tool calls as raw text:

```text
<function=analyze_file>{"filename":"sales.csv"}</function>
```

…instead of using the OpenAI structured `tool_calls` field. Without rescue, this leaks into the spoken response and confuses the user. The rescue parser:

1. Detects the pattern in `resp.content`
2. Parses out the function name + JSON arguments
3. Promotes them into real `ToolCall` objects
4. Strips the leakage from the spoken text
5. Executes the tool as if the model had emitted it correctly

---

## 5. Performance characteristics

| Operation | Median latency |
|---|---|
| STT (10s clip) | ~800 ms |
| LLM round-trip (text only) | ~700 ms |
| LLM round-trip (with tool call) | ~1.4 s |
| Tool execution (cached) | <50 ms |
| Tool execution (cold web) | 200–600 ms |
| TTS synthesis (50 words) | ~300 ms |
| **Total: voice in → voice out** | **~2.5 s** |

Memory footprint: ~120 MB resident (FastAPI + MCP combined, idle).

---

## 6. Scaling considerations

The current design assumes a single user / single host. To scale:

- **Sessions** — `_agents: dict[sid → JarvisAgent]` is in-memory. Move to Redis for horizontal scaling.
- **File storage** — `%TEMP%` is local disk. Move to S3 / object storage for multi-host.
- **Memory DB** — single SQLite file, fine for one user. For multi-tenant, switch to PostgreSQL with a `user_id` partition key.
- **MCP server** — currently one process. Could run multiple instances behind a load balancer if tool catalogues are stateless.

The bottleneck is always the LLM provider's rate limit, not local compute.
