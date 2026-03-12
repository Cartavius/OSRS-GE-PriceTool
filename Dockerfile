FROM python:3.12-slim

WORKDIR /app

COPY server.py server.config.json Index.html Styles.css app.js stats.html stats.js ./

EXPOSE 8080

CMD ["python", "server.py", "--host", "0.0.0.0", "--config", "server.config.json"]
