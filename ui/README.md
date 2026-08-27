# Z Money — UI

Vite + React + TypeScript + Tailwind v4 frontend for Z Money. See the
project root [README.md](../README.md) for what Z Money is and how to run
the backend it talks to.

```bash
npm install
npm run dev
```

Expects the API at `http://localhost:8000` (see `../api/server.py`).

## Structure

```
src/routes/       one component per sidebar screen
src/components/   shared UI atoms + per-screen subcomponents (components/briefing/, components/settings/)
src/api/          fetch wrappers for the FastAPI backend
src/types/        TypeScript types mirroring the backend's dataclasses/Pydantic models
src/lib/          formatting helpers
```

No component library, by design — see the root spec's §7 (avoid a
templated-dashboard look). Dark theme only; design tokens live in
`src/index.css`.
