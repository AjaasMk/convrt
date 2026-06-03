---
title: Convrt SpiceNutrition AI Agent
emoji: 💪
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: WhatsApp AI sales agent for SpiceNutrition supplements
---

# Convrt — WhatsApp AI Sales Agent (SpiceNutrition)

A full-stack AI sales agent demo for small businesses, configured for the
**SpiceNutrition** supplement store.

## Features
- 🤖 AI customer chat (product search, orders, returns, recommendations, dosage Q&A)
- 📊 Staff dashboard (orders, revenue, escalations)
- 📦 Inventory manager (stock levels, low-stock alerts)
- 🧑‍💼 Human handoff — staff can take over any chat live; AI auto-resumes
- 🛡️ Per-customer rate limiting (anti-spam)

## Stack
Python · LangGraph · Gemini Flash (via LangChain) · FastAPI · SQLite · ChromaDB · Gradio

## Configuration (set these as Space **Secrets**, not in code)
| Secret | Purpose |
|--------|---------|
| `GEMINI_API_KEY` | Google Gemini API key |
| `GEMINI_MODEL` | e.g. `gemini-flash-latest` |
| `APP_USERNAME` | Dashboard login username |
| `APP_PASSWORD` | Dashboard login password |

> The database and vector store are seeded automatically on startup.
