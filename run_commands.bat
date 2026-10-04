@echo off
:: MarketRadarAI - Example CLI Commands
:: This script shows how to run the pipeline commands via the command line interface.

:: Ensure you are in the backend directory
cd backend

:: 1. Setup the database schema
echo "Running migrations..."
uv run python -m app.cli migrate

:: 2. Seed the database with demo data (run this first if you haven't)
echo "Seeding Demo Data..."
uv run python -m app.cli seed-demo

:: 2. Run the entire pipeline for all active sources
echo "Running full pipeline for all sources..."
uv run python -m app.cli run-all

:: 3. (Optional) Run the pipeline for a specific source ID
:: Replace <source_id> with an actual UUID from your database
:: echo "Running pipeline for specific source..."
:: uv run python -m app.cli run-source <source_id>

:: 4. Generate the daily brief
echo "Generating daily brief for Northwind Analytics..."
uv run python -m app.cli brief northwind --no-deliver

:: 5. Dispatch the scheduler (one tick)
echo "Dispatching scheduler..."
uv run python -m app.cli dispatch

echo "Done!"
