# Build from the REPOSITORY ROOT so both relay/ and client/ are in context:
#   docker build -f relay/Dockerfile -t pocketdesk-relay .
# (the docker-compose.yml here already sets context to the repo root.)
FROM python:3.12-slim

WORKDIR /app
COPY relay/requirements.txt /app/relay/requirements.txt
RUN pip install --no-cache-dir -r /app/relay/requirements.txt

COPY relay/ /app/relay/
COPY client/ /app/client/

# Drop privileges.
RUN useradd --system --uid 10001 relay
USER relay

EXPOSE 9000
ENTRYPOINT ["python", "-m", "relay", "--host", "0.0.0.0", "--port", "9000"]
