# VisionSpark 👁️⚡

> **Real-Time Multimodal Accessibility Assistant**

VisionSpark is an interactive accessibility solution designed to help visually impaired individuals navigate and process physical text, product packaging, and everyday objects in real time.

---

## 📌 Project Overview

Navigating non-digital printed information—such as product allergen lists, expiration dates, or physical signs—remains a major challenge for visually impaired users. 

**VisionSpark** solves this by converting complex visual input from everyday objects into instant, clear audio feedback, providing users with a fast and intuitive voice interface.

---

## 🛠️ Core Tech Stack

* **Frontend:** Vue 3 & Vite
* **Backend:** FastAPI (Python)
* **AI Models:** Meta Model API (**Muse Spark 1.3** & **SAM 3.1**)

---

## ✨ Features

* **Image segmentation** — upload a photo, name an object (e.g. `dog`), and
  SAM 3.1 returns bounding boxes drawn over the image.
* **Camera capture** — frame an object with your device camera and capture
  a still photo straight into the segmentation and Q&A workflow.
* **Visual question answering** — ask about the full image or zoom into
  a detected SAM region; Muse Spark 1.3 answers in plain text.
* **Read aloud** — the answer can be spoken via the browser's built-in
  speech synthesis (no extra service or key needed).
* **Settings dialog** — the header gear button opens language, color theme
  (system/light/dark), and voice preferences: woman's/man's/automatic or
  specific system voice (remembered per language), tone and speaking rate,
  auto-read toggles, and a preview button. Remembered on-device.
* **Audio-first wizard** — one action per screen (Photo → Check → Ask →
  Listen) with spoken status updates and a sticky Back/Continue/audio bar.
* **One-tap questions** — four preset question buttons (read label,
  allergens, expiry date, "What is in this image?") that ask immediately
  with no typing needed.
* **Languages** — the whole UI (English, French, Spanish, Greek,
  Chinese) plus spoken answers and model answers in the selected language.
* **Accessible UI** — native controls, keyboard support, labeled SVG overlay,
  and live-region status updates.

## 🚀 Quick Start

Prerequisites: `uv`, Node.js with `npm`, and a Meta Model API key.

```bash
# 1. Backend API key (backend-only, never committed)
cp backend/.env.example backend/.env
# edit backend/.env and set MODEL_API_KEY=<your key>

# 2. One-shot start (Linux/macOS/WSL)
./full-start.sh
# Windows: double-click full-start.bat | macOS: double-click full-start.command
```

Then open **http://localhost:5173/** (backend API at
**http://localhost:8000**, docs at `/docs`).

Full instructions, manual start commands, and troubleshooting: see
**[MANUAL.md](MANUAL.md)**. AI coding agents: see
**[AGENTS.md](AGENTS.md)** (working agreement).

## 🗂️ Project Structure

```text
├── backend/          # FastAPI + uv (Python 3.12)
│   ├── app/          # main.py, meta_api.py, settings.py
│   ├── tests/        # pytest suite (upstream always mocked)
│   ├── pyproject.toml / uv.lock / .python-version
│   └── .env.example  # placeholder only
├── frontend/         # Vue 3 + Vite + npm
│   └── src/App.vue   # upload, overlay, Q&A, speech UI
├── MANUAL.md         # how to run the program
├── AGENTS.md         # AI agent working agreement
└── full-start.*      # one-shot launch scripts
```

## 🔌 API Endpoints

| Method & Path     | Input                          | Output                          |
|-------------------|--------------------------------|---------------------------------|
| `GET /health`     | —                              | `{"status": "ok"}`              |
| `POST /api/segment` | image (JPEG/PNG/WebP ≤ 5 MiB) + `prompt` | `{model, status, output_text, boxes}` |
| `POST /api/ask`   | image + required `question`    | `{model, status, answer}`       |