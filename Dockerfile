# Runs the Streamlit dashboard (which talks to auth/paper_trading/backtesting
# directly, in-process - no separate backend container needed for this to
# work end to end). DATA_DIR is expected to point at a mounted persistent
# volume (see fly.toml) so the DuckDB file and downloaded price data survive
# restarts and redeploys - without that, everything resets on every deploy.
FROM python:3.12-slim

WORKDIR /app

# duckdb/pyarrow ship prebuilt manylinux wheels, so no compiler toolchain is
# needed here - keep the image lean.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATA_DIR=/data
ENV LOG_LEVEL=INFO

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "app/dashboard.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
