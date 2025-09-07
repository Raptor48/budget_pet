FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Copy requirements first for better caching
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application
COPY . /app

# Expose port (Railway will set PORT env var)
EXPOSE 8000

# Default command will be overridden by Railway service start command
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
