# Use python3 as the default interpreter
PYTHON = python3

# Define the source files to be checked
SOURCES = main.py src/
TESTS_DIR = tests/
ALL_SOURCES = $(SOURCES) $(TESTS_DIR)

.PHONY: help install format lint security-check test quality clean sync-portfolio push-config pull-config save-snapshot etf-details stock-details migrate analyze-opportunity sync-fundamentals exposure analyze-quality dashboard update-finance project-growth report

# ==============================================================================
# 🛠️ Setup, Maintenance & Quality Gates
# ==============================================================================
# Installs the package and its development dependencies in editable mode.
install:
	$(PYTHON) -m pip install -e .[dev]

# Automatically formats code with Black and fixes linting/imports with Ruff.
format:
	@echo "Formatting code (black)..."
	$(PYTHON) -m black $(ALL_SOURCES)
	@echo "Fixing lint issues and sorting imports (ruff)..."
	$(PYTHON) -m ruff check --fix $(ALL_SOURCES)

# Runs code formatting verification, Ruff linting, and Mypy static type checking.
lint:
	@echo "Running formatter check (black)..."
	$(PYTHON) -m black --check $(ALL_SOURCES)
	@echo "Running linter (ruff)..."
	$(PYTHON) -m ruff check $(ALL_SOURCES)
	@echo "Running static type checker (mypy)..."
	PYTHONPATH=src $(PYTHON) -m mypy $(SOURCES)

# Executes static security vulnerability analysis (Bandit) and dependency checks (Pip-Audit).
security-check:
	@echo "Running SAST security scan (bandit)..."
	$(PYTHON) -m bandit -r $(SOURCES)
	@echo "Checking dependencies for vulnerabilities (pip-audit)..."
	$(PYTHON) -m pip_audit

# Runs unit tests using Pytest with branch coverage reporting.
test:
	@echo "Running unit tests with coverage..."
	PYTHONPATH=src $(PYTHON) -m pytest --cov=src --cov=main --cov-report=term-missing --cov-report=xml --cov-report=html $(TESTS_DIR)

# Orchestrates the full CI quality gate combining linting, security checks, and unit tests.
quality: lint security-check test

# Cleans temporary Python compilation cache files, test reports, and local caches.
clean:
	@echo "Cleaning Python temporary cache files and test reports..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	rm -f data/etf_cache.json

# ==============================================================================
# 📈 Project Utils
# ==============================================================================
# Migrates legacy JSON portfolio and history datasets into the central SQLite database.
migrate:
	PYTHONPATH=. $(PYTHON) src/migrate_json_to_sqlite.py

# Pushes local configuration files to the remote Google Drive repository.
push-config:
	PYTHONPATH=src $(PYTHON) main.py push-config

# Pulls configuration files from the remote Google Drive repository to local storage.
pull-config:
	PYTHONPATH=src $(PYTHON) main.py pull-config

# Synchronizes portfolio data by executing JSON to SQLite migration and pushing configs to Google Drive.
sync-portfolio:
	PYTHONPATH=. $(PYTHON) src/migrate_json_to_sqlite.py
	PYTHONPATH=src $(PYTHON) main.py push-config

# Computes portfolio valuation, records a historical snapshot in SQLite, and backs up to Google Drive.
save-snapshot:
	PYTHONPATH=src $(PYTHON) main.py save-snapshot

# Inspects detailed composition, TER, holdings, and sector/country breakdowns for an ETF.
etf-details:
	PYTHONPATH=src $(PYTHON) main.py etf-details

# Inspects fundamental financial metrics for a stock ticker or ISIN.
stock-details:
	PYTHONPATH=src $(PYTHON) main.py stock-details

# Runs consolidated look-through exposure checks including individual company limits (max 15%).
exposure:
	$(PYTHON) main.py exposure-check

# Synchronizes fundamental history snapshots for both stocks and ETFs into SQLite history.
sync-fundamentals:
	PYTHONPATH=src $(PYTHON) main.py sync-fundamentals

# Fully updates finances.db with fundamental data, portfolio snapshot, exposure checks, and opportunity analysis before or after trading.
update-finances:
	$(MAKE) pull-config
	$(MAKE) migrate
	$(MAKE) sync-fundamentals
	$(MAKE) save-snapshot
	$(MAKE) exposure
	$(MAKE) analyze-quality
	$(MAKE) analyze-opportunity
	$(MAKE) dashboard FLAGS="--export-plots"
	$(MAKE) report FLAGS="--no-browser"
	$(MAKE) push-config

# Orchestrates portfolio opportunity_evaluation ranking, quantitative scoring, and Google Gemini AI rebalancing analysis.
# Accepts optional CLI flags via FLAGS variable (e.g., make opportunity FLAGS="--skip-ai -v"):
#   -t, --targets-file PATH : Path to wishlist targets JSON file (default: data/portfolio_targets.json)
#   -p, --portfolio-file PATH: Path to active holdings JSON file (default: data/portfolio.json)
#   --skip-ai               : Run quantitative scoring matrix only (bypasses Gemini AI analysis)
#   -v, --verbose           : Display granular factor score breakdowns (Dip Sc, Cost Sc, Gap Sc)
#   -o, --output-csv PATH   : CSV export destination path (default: output/opportunity_output_22_08_2026.csv)
analyze-opportunity:
	PYTHONPATH=src $(PYTHON) main.py opportunity_evaluation $(FLAGS)

# Evaluates absolute quality tiers, comprehensive fundamental metrics, and diagnostic Bull/Bear cases.
analyze-quality:
	PYTHONPATH=src $(PYTHON) main.py analyze-quality $(TICKER)

# Displays historical performance dashboard and analytics executive summary.
# Accepts optional CLI flags via FLAGS variable (e.g., make dashboard FLAGS="--export-plots" or FLAGS="-t AAPL"):
dashboard:
	PYTHONPATH=src $(PYTHON) main.py dashboard show $(if $(TICKER),-t $(TICKER)) $(FLAGS) --export-plots

# Projects portfolio growth over 10, 20, and 30-year horizons.
# Example usage: make project-growth FLAGS="--monthly-contribution 500 --compare-scenarios"
project-growth:
	PYTHONPATH=src $(PYTHON) main.py project-growth $(FLAGS) --compare-scenarios --monthly-contribution 500

# Generates a dark-theme HTML executive portfolio report in output/reports/.
# Use FLAGS="--no-browser" to suppress browser launch (e.g. in CI).
report:
	PYTHONPATH=src $(PYTHON) main.py report generate $(FLAGS)
