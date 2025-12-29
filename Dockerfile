# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Create data directory structure
RUN mkdir -p data/uploads

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run the application
CMD ["python", "buddai_v3.2.py", "--server", "--port", "8000"]