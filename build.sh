docker stop line-bot-summary
docker rm line-bot-summary
docker image prune -af
docker build -t line-bot-summary .
docker run -dp 8111:5000 --env-file .env line-bot-summary
