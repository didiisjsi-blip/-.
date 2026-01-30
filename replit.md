# WormGPT Discord Bot

## Overview

This is a Discord bot that integrates with the OpenRouter API to provide AI-powered chat responses. The bot uses a Flask-based keep-alive server to maintain uptime on Replit's hosting environment. It connects to Discord using the discord.py library and processes messages through various AI models available via OpenRouter.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Components

**Entry Point (`main.py`)**
- Initializes the keep-alive web server before starting the bot
- Imports the configured bot instance from the main module
- Validates environment variables before launch

**Bot Logic (`GPT_WORM_V2.py`)**
- Discord bot implementation using discord.py with commands extension
- Handles message events and command processing
- Integrates with OpenRouter API for AI responses
- Uses JSON files for configuration persistence (`wormgpt_configmre.json`)
- Uses SQLite for data storage (sqlite3 import present)
- Includes language detection via `langdetect` library

**Keep-Alive Server (`keep_alive.py`)**
- Flask web server running on port 8080
- Runs in a separate thread to prevent blocking the Discord bot
- Provides a health check endpoint for external monitoring services
- Essential for maintaining bot uptime on Replit

### Configuration Management

- **Environment Variables**: Discord token (`DISCORD_TOKEN`), OpenRouter API key (`OPENROUTER_API_KEY`), and webhook URL (`WEBHOOK_URL`)
- **JSON Configuration**: Guild-specific settings stored in `guilds.json` and bot config in `wormgpt_configmre.json`
- **Text Files**: System prompt loaded from `system-prompt.txt`

### Design Decisions

1. **Thread-based Keep-Alive**: Separates the web server from the async Discord bot to avoid blocking
2. **Environment Variable Security**: Sensitive tokens stored as environment variables rather than hardcoded
3. **Modular File Structure**: Separates concerns between bot logic, configuration, and server components

## External Dependencies

### APIs and Services

| Service | Purpose | Configuration |
|---------|---------|---------------|
| Discord API | Bot messaging and commands | `DISCORD_TOKEN` env var |
| OpenRouter API | AI model access (default: Gemini 2.5 Flash) | `OPENROUTER_API_KEY` env var |
| Discord Webhooks | Guild management notifications | `WEBHOOK_URL` env var |

### Python Packages

- `discord.py` - Discord bot framework with commands extension
- `flask` - Web server for keep-alive functionality
- `aiohttp` - Async HTTP client for API requests
- `requests` - Synchronous HTTP requests
- `langdetect` - Language detection for responses
- `sqlite3` - Local database storage (built-in)

### Data Storage

- **SQLite**: Used for persistent data storage
- **JSON Files**: Configuration and guild data
- **Text Files**: System prompts and templates

### Default Configuration

- Base URL: `https://openrouter.ai/api/v1`
- Default Model: `google/gemini-2.5-flash`
- Default Language: Thai
- Web Server Port: 8080