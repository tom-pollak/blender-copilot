# Blender Copilot

Extension to generate 3D models from Blender.

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
