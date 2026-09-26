# Веб-версия AstroCalendar.
#
# Образ намеренно тонкий: эфемериды и каталоги (около 200 МБ) в него не
# вшиваются, а лежат в томе рядом. Иначе каждое обновление кода тянуло бы
# заново сотни мегабайт данных, которые не менялись.
#
# Python 3.12, а не системный 3.10: часть кода рассчитана на новые аннотации,
# и привязываться к версии дистрибутива ни к чему.
FROM python:3.12-slim

# tini — чтобы сигналы доходили до процесса и контейнер останавливался сразу,
# а не по таймауту. curl нужен для проверки здоровья.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ASTROCAL_HOME=/srv/astrocalendar

WORKDIR /app

# Зависимости отдельным слоем: правка кода не пересобирает их заново
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY src ./src
COPY scripts ./scripts

ENV PYTHONPATH=/app/src

# Данные, кэш и архив выпусков — снаружи, в томе
RUN mkdir -p /srv/astrocalendar/data

EXPOSE 8120

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8120/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "astrocal_web.app:get_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8120", \
     "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--timeout-keep-alive", "65"]
