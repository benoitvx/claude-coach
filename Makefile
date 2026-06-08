.PHONY: install validate test test-one lint format typecheck precommit-install clean

# Détecte uv ; sinon l'installe via le script officiel astral.
# Le script écrit dans ~/.local/bin (par défaut) ; on l'ajoute au PATH pour la suite.
install:
	@if ! command -v uv >/dev/null 2>&1; then \
		echo ">> uv absent, installation..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	else \
		echo ">> uv déjà présent ($$(uv --version))"; \
	fi
	@export PATH="$$HOME/.local/bin:$$PATH" && uv sync

validate: lint typecheck test

test:
	uv run pytest

test-one:
	@if [ -z "$(F)" ]; then echo "Usage: make test-one F=tests/test_xxx.py"; exit 1; fi
	uv run pytest $(F)

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

precommit-install:
	uv run pre-commit install

clean:
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
