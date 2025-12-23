# Blender Copilot

Extension to generate 3D models from Blender.

## Demo

https://github.com/user-attachments/assets/8aca25df-7499-411b-8400-2c10c7288bb6

## Setup

### Environment

```bash
uv sync
```

Fill in the `.env` file with Google OAuth credentials, Stripe keys, and Modal API key.

```bash
cp .env.template .env
```

## Development

```bash
uv run uvicorn server.app:app --reload
```
