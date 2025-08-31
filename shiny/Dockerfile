# Use conda base image
FROM continuumio/miniconda3

# Set working directory
WORKDIR /app

# Copy environment.yml and app files
COPY environment.yml .
COPY . .

# Install dependencies and create conda env
RUN conda env create -f environment.yml

# Use bash shell so we can source conda properly
SHELL ["/bin/bash", "-c"]

# Ensure conda is initialized on shell startup
RUN echo "source /opt/conda/etc/profile.d/conda.sh" >> ~/.bashrc

# Expose the port Shiny will use
EXPOSE 8000

# Use the full path to shiny in CMD with conda run to avoid PATH issues
# CMD ["conda", "run", "-n", "shiny_app", "/opt/conda/envs/shiny_app/bin/shiny", "run", "--host", "0.0.0.0", "--port", "8000", "--reload", "app.py"]
CMD ["conda", "run", "-n", "shiny_app","/opt/conda/envs/shiny_app/bin/shiny", "run", "--host", "0.0.0.0", "--port", "8000", "app.py"]