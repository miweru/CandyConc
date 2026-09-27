# CandyConc web interface

The web interface of CandyConc: Vue 3, TypeScript, Vite, Tailwind CSS, Pinia,
and vue-i18n. The CandyConc server serves the built interface itself, so a
normal installation needs neither Node.js nor this folder.

To work on the interface, set up the development environment as described in
[Set up a development environment](../docs/contribute/development-setup.md).
In short, with a CandyConc server running on port 8010:

```bash
npm ci
npm run dev
```

| Command | What it does |
| --- | --- |
| `npm run dev` | development server with reload, forwards `/api` and `/mcp` to the CandyConc server (port from `CANDYCONC_BACKEND_PORT`, default 8010) |
| `npm run build` | type check with `vue-tsc` and production build into `dist/`, with `THIRD_PARTY_LICENSES.txt` |
| `npx vitest run` | unit tests |
| `npm run test:e2e` | browser tests with Playwright |

`python packaging/build_web.py` at the root of the repository builds the
interface into the Python package. The tests are described in
[Run the tests](../docs/contribute/tests.md), the structure of the interface
in [Architecture for contributors](../docs/contribute/architecture-for-contributors.md).
