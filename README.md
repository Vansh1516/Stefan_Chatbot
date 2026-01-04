# BotBro: Sarcastic AI Roommate Agent 🤖🇩🇪

An intelligent Telegram bot designed to manage the daily friction of shared flat (WG) living. Unlike simple script bots, BotBro utilizes a **ReAct (Reason + Act)** agent architecture to autonomously use tools, managing cleaning schedules, setting reminders, and performing web searches—all while maintaining a sarcastic, German-infused persona.

## 🚀 Features

-   **🧠 ReAct Agent Engine:** Uses Groq (Llama 3.3) to "think" before speaking, allowing it to decide when to use specific tools (Calculator, Search, Schedule) or just chat.
-   **📅 Roster Management:** Embeds the flat's cleaning CSV to automatically track and announce whose turn it is for kitchen or bathroom duties.
-   **⏰ Async Reminders:** Leverages the Telegram `JobQueue` to parse natural language requests (e.g., "Remind me in 10 mins") and set background timers.
-   **🔎 Web Search:** Performs real-time DuckDuckGo searches to answer questions about news or facts.
-   **🎭 Custom Persona:** configured to be chill, sarcastic, and slightly German ("Genau!", "Scheiße..."), making it feel like a roommate rather than a utility.

## 🛠️ Tech Stack

-   **Core:** Python 3.10+, AsyncIO
-   **Interface:** `python-telegram-bot`
-   **LLM Inference:** Groq API (Llama-3.3-70b-versatile)
-   **Search:** `duckduckgo-search` (DDGS)
-   **Deployment:** Systemd Service on Linux VPS

## 📂 Project Structure

-   `bot.py`: The main agent loop, tool definitions, and personality handler.
-   `cleaning_schedule.csv`: (Embedded) Data for the rotating cleaning roster.