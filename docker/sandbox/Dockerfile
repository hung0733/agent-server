FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src

RUN useradd --create-home --uid 10001 sandbox && mkdir -p /workspace && chown -R sandbox:sandbox /workspace /app

USER sandbox

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "sandbox_agent_runner:app", "--host", "0.0.0.0", "--port", "8080"]
