# Use official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /

# Install dependencies
COPY requirements.txt /
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . /

# Expose port
EXPOSE 8000

# Run API
CMD ["uvicorn", "rag_api:app", "--host", "0.0.0.0", "--port", "8000"]
