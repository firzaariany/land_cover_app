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

# Expose TiTiler port
EXPOSE 8001

# Activate conda environment again and run Titiler
CMD ["conda", "run", "-n", "shiny_land", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", "8001"]


