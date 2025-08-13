# Step 1: Use an official Python runtime as a parent image.
# 'slim' is a smaller version, great for production.
FROM python:3.11-slim

# Step 2: Set the working directory inside the container.
WORKDIR /app

# Step 3: Copy the new dependencies file.
COPY requirements.txt .

# Step 4: Install the dependencies using pip.
RUN pip install --no-cache-dir -r requirements.txt

# Step 5: Copy the rest of your application's code.
COPY . .

# Step 6: Expose the port the app runs on.
EXPOSE 8000

# Step 7: Define the command to run when the container starts.
# No need to activate Conda anymore.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]