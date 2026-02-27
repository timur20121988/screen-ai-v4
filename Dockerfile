FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure the installer output directory exists (though it should be in git)
RUN mkdir -p installer_output

# Expose port for health checks and API
EXPOSE 8080

# Run the bot
CMD ["python", "bot.py"]
