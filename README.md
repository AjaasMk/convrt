---
title: Convrt SpiceNutrition AI Agent
emoji: 💪
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: WhatsApp AI sales agent for small businesses
---

# 💪 Convrt — WhatsApp AI Sales Agent

> **AI agents that turn conversations into customers.**

Convrt is a production-grade **AI sales agent** for small businesses. It chats with
customers (on WhatsApp in production, or a built-in web simulator), understands what they
want, checks live inventory, recommends products, takes orders, collects payment via UPI QR,
handles returns, and hands off to a human when needed.

This repo ships a fully working demo configured for a supplement store, **SpiceNutrition**.

**🔗 Live demo:** https://ajaasmk-convrt.hf.space

---

## ✨ Features

- 🤖 **Agentic AI** — a LangGraph agent that *reasons* about which action to take (not fixed flows)
- 🛒 **Real commerce** — live inventory, order placement, order tracking, returns, waitlists
- 💳 **In-chat payments** — generates a UPI payment QR + link after each order
- 🎥 **Vision** — customer uploads a reel screenshot → agent identifies & matches the product
- 🧑‍💼 **Human handoff** — staff take over any chat (AI auto-pauses), AI resumes after inactivity
- 🧠 **RAG knowledge base** — answers policy/FAQ/dosage questions from a knowledge file
- 🛡️ **Safety** — per-customer rate limiting, spam guards, medical-escalation rules
- 📊 **Staff dashboard** — orders, revenue, escalations, inventory, live conversations
- 🔌 **Multi-provider LLM** — Groq (default), Google Gemini, or Anthropic Claude — switch via env

## 🏗️ Architecture

```
Customer (WhatsApp / web)
        │
        ▼
FastAPI  ──►  Rate limiter ──►  LangGraph agent ──►  Tools ──►  SQLite (orders, inventory)
(api/main.py)                   (Groq LLM +          │          ChromaDB (RAG)
  • web UI                       vision)             │          Vision model (images)
  • JSON APIs                                        ▼
  • auth                                       Human handoff (staff takeover)
```

## 🧰 Tech stack

Python · **FastAPI** · **LangGraph** · **Groq** (Llama 3.3 / Llama 4 vision) ·
SQLite · ChromaDB (RAG) · HTML + Tailwind frontend · Docker · Hugging Face Spaces

## 📁 Project structure

```
convrt/
├── agent/
│   ├── graph.py        # LangGraph agent + chat() entrypoint
│   ├── nodes.py        # LLM provider selection + system prompt
│   ├── tools.py        # 10 tools (search, inventory, orders, payment, etc.)
│   ├── vision.py       # reel-screenshot → product description
│   ├── handoff.py      # human takeover logic
│   ├── rate_limiter.py # per-customer anti-spam
│   └── state.py        # conversation state
├── api/main.py         # FastAPI: web UI + JSON APIs + auth + payment QR
├── frontend/index.html # custom Tailwind single-page UI (chat / dashboard / inventory)
├── agency/index.html   # Convrt agency marketing landing page
├── database/           # SQLite schema + SpiceNutrition seed data
├── knowledge/          # RAG knowledge base + vector store
├── config.yaml         # business configuration (name, brand, payment, policies)
├── Dockerfile          # runs uvicorn on port 7860
└── requirements.txt
```

## 🔑 Environment variables

Create a `.env` file in the project root (it is gitignored — never commit it):

```bash
# LLM provider — auto-detected; priority GEMINI > GROQ > ANTHROPIC.
# Set LLM_PROVIDER to force one.
LLM_PROVIDER=groq

# Groq (free, recommended) — https://console.groq.com
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile

# (optional alternatives)
# GEMINI_API_KEY=your_gemini_key
# ANTHROPIC_API_KEY=your_anthropic_key

# Dashboard login
APP_USERNAME=your_username
APP_PASSWORD=your_password

# Deployment (Hugging Face) — for the deploy script only
# HF_TOKEN=your_hf_write_token
```

On Hugging Face, set these as **Space Secrets** (not in the repo).

## 🚀 Run locally

```bash
pip install -r requirements.txt
# add your .env (see above)
uvicorn api.main:app --host 0.0.0.0 --port 7860
# open http://localhost:7860  (login with APP_USERNAME / APP_PASSWORD)
```

The database and vector store seed automatically on first run.

## ☁️ Deploy

Runs as a **Hugging Face Docker Space** (this repo includes the `Dockerfile` and the
`sdk: docker` front-matter above). Push the repo to a Space and set the env vars as Secrets.
Also deployable to Railway, Render, Fly.io, or any container host.

## 🏷️ About

Convrt is the flagship service of an AI agency that builds custom AI agents for businesses.
This supplement-store build (SpiceNutrition) is a reference implementation.

---

*Built with the Claude Agent SDK.*
