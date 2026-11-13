FROM node:22-slim AS web
WORKDIR /mvp/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY migrations migrations
COPY --from=web /mvp/web/dist web/dist
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
