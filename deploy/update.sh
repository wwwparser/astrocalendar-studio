#!/usr/bin/env bash
# Обновление веб-версии на сервере.
#
#     ssh podcast '/data/astrocalendar/repo/deploy/update.sh'
#
# Забирает свежий код, пересобирает образ и перезапускает контейнер.
# Данные, архив выпусков и список пользователей лежат в томе и не трогаются.
set -euo pipefail

ROOT="/data/astrocalendar/repo"
cd "$ROOT"

echo "→ Забираем код"
git fetch --quiet origin
git reset --hard origin/main --quiet
git log --oneline -1

cd "$ROOT/deploy"

if [ ! -f .env ]; then
    echo "Нет deploy/.env с ASTROCAL_WEB_SECRET — остановился, чтобы не"
    echo "поднять сайт со случайным ключом сессий."
    exit 1
fi

echo "→ Собираем образ"
docker compose build

echo "→ Перезапускаем"
docker compose up -d

echo "→ Ждём готовности"
for attempt in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8120/health >/dev/null 2>&1; then
        echo "   готово за ${attempt}0 секунд или быстрее"
        break
    fi
    sleep 10
done

echo "→ Состояние"
docker ps --filter name=astrocalendar --format "   {{.Names}}  {{.Status}}"
curl -fsS http://127.0.0.1:8120/health && echo
