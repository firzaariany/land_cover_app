# Use conda base image
FROM continuumio/miniconda3

# Set working directory
WORKDIR /app

# Copy requirements file
COPY environment.yml .

# Install dependencies
RUN conda env create -f environment.yml

# Ensure the conda environment is activated
SHELL ["conda", "run", "-n", "shiny_land", "/bin/bash", "-c"]

# Copy app files
COPY . .

# Expose Shiny port
EXPOSE 8000

# Activate conda environment again and run Shiny
CMD ["conda", "run", "-n", "shiny_land", "shiny", "run", "--host", "0.0.0.0", "--port", "8000", "--reload", "app.py"]
