# Contributing to DevFlow Kit

Thanks for your interest in contributing!

## Development setup

```bash
git clone https://github.com/manas-rai/devflow-kit.git
cd devflow-kit
pip install -e ".[dev]"
```

## Running tests

```bash
pytest tests/ -v
```

## Adding a new agent

1. Create `agents/your_agent.py` following the pattern in `agents/refine.py`
2. Create a prompt template in `prompts/your-agent.md`
3. Create a workflow in `.github/workflows/your-agent.yml`
4. Add tests in `tests/test_your_agent.py`
5. Update `README.md` and `docs/DOCUMENTATION.md`

## Code style

- Python 3.12+, type hints on all functions
- Format with `ruff format .`
- Lint with `ruff check .`
- Keep dependencies minimal — only `httpx` and `pydantic` in core

## Pull requests

- One feature per PR
- Include tests
- Update documentation if behavior changes
