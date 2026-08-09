# Contributing

AgentFlow welcomes focused issues and pull requests that strengthen its three bounded workflows: cited question answering, document comparison, and executive brief generation.

## Development setup

Requirements:

- Python 3.12
- `uv`
- Node.js 22 or newer
- Docker with Compose

Install local dependencies:

```sh
uv sync --all-groups
npm --prefix frontend ci
```

Run the local stack:

```sh
docker compose up --build
```

Run the quality gates:

```sh
make check
```

## Pull requests

- Keep changes narrow and explain the user-visible or operational reason.
- Add tests for new behavior and failure paths.
- Update architecture records when a component boundary changes.
- Include benchmark inputs and raw outputs for performance claims.
- Never add secrets, private documents, generated chain-of-thought, or personal application material.

By contributing, you agree that your work is licensed under the MIT License.
