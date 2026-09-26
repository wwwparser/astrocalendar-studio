# Веб-версия

Тот же редактор выпуска, что в настольной программе, только в браузере и с
входом по паролю. Полезна, когда календарь ведут с разных машин или когда
ставить приложение некуда.

Рабочий адрес: **https://astrocalendar.optegra.ru**

---

## Что умеет

- **Рассчитать месяц** — кнопка на главной. Расчёт идёт на сервере 10–15 минут,
  страницу можно закрыть: результат сохранится и появится в списке.
- **Отобрать события** — галочка у каждой строки, счётчик знаков в посте
  пересчитывается сразу.
- **Переписать формулировку** — текст события правится прямо в таблице,
  расчётный вариант сохраняется отдельно и возвращается одной кнопкой.
- **Фильтры** — ранги значимости, категории событий, значки вместо ▪️.
- **Публикация** — готовый текст, разбитый по лимиту Telegram, с кнопкой
  копирования каждой части.
- **Проверка** — события с пометками REVIEW и WARN, полный отчёт файлом.
- **Скачать** — текст, markdown, JSON, протокол расчёта, отчёт проверки.
- **LIVE** — лента открытий и уточнений.

Чего в вебе нет: карт неба и полос видимости, отправки в Telegram из
интерфейса. И то и другое есть в настольной версии.

---

## Как всё устроено

```
браузер → Apache (443, сертификат Let's Encrypt)
            │  ProxyPass
            ↓
       контейнер astrocalendar-web  (127.0.0.1:8120)
            │  uvicorn + FastAPI
            ↓
       том /data/astrocalendar/data
       эфемериды · каталоги · кэш · архив выпусков · пользователи
```

Порт приложения слушается только на localhost: наружу сайт смотрит через
Apache, который держит сертификат.

**Расчёт вне запроса.** Месяц считается дольше любого разумного таймаута,
поэтому кнопка ставит задачу в очередь, а страница опрашивает прогресс.
Одновременно выполняется одна задача: расчётное ядро держит эфемериды в кэшах
уровня модуля, и две параллельные копии мешали бы друг другу. Повторное
нажатие переиспользует уже идущую задачу, а не запускает вторую.

**Результат на диске.** Рассчитанный выпуск целиком ложится в
`data/issues/ГГГГ-ММ.json`: события, редакторские решения, флаги проверок.
Любая страница поднимает его оттуда за миллисекунды. Формат — JSON, а не
pickle: архив должен читаться и после того, как в коде переименуют поле.

---

## Вход и пользователи

Сайт закрыт целиком: без входа не отдаётся ничего, кроме формы входа.
Регистрации нет, пользователей заводит администратор.

```bash
ssh podcast
cd /data/astrocalendar/repo/deploy
docker compose exec web python scripts/web_user.py list
docker compose exec web python scripts/web_user.py add <имя>
docker compose exec web python scripts/web_user.py passwd <имя>
docker compose exec web python scripts/web_user.py remove <имя>
```

Пароль спрашивается скрытым вводом. Передавать его аргументом нельзя
намеренно: аргументы видны в списке процессов и остаются в истории оболочки.

Как это защищено: пароли хранятся как scrypt-хэш с индивидуальной солью,
сам пароль не пишется никуда. Ответ при неверном логине и при неверном пароле
одинаковый — иначе форма подсказывает, какие логины существуют. После пяти
неудачных попыток вход с этой пары «логин + адрес» закрывается на четверть
часа. Сессия живёт двенадцать часов.

---

## Развёртывание с нуля

Нужны: домен, направленный на сервер, Docker, Apache с модулями `proxy_http`,
`ssl`, `rewrite`, `headers`.

```bash
# 1. Код на диск, где есть место
sudo mkdir -p /data/astrocalendar && sudo chown $USER /data/astrocalendar
cd /data/astrocalendar
git clone https://github.com/wwwparser/astrocalendar-studio.git repo

# 2. Ключ подписи сессий
cd repo/deploy
python3 -c "import secrets; print('ASTROCAL_WEB_SECRET=' + secrets.token_urlsafe(48))" > .env
chmod 600 .env

# 3. Сборка и запуск
docker compose build && docker compose up -d
curl -fsS http://127.0.0.1:8120/health

# 4. Данные: эфемериды и каталоги, около 138 МБ, один раз
docker compose exec web python -c "
import sys; sys.path.insert(0, '/app/src')
from astrocal_app import bootstrap
print(bootstrap.download_all(required_only=True))"

# 5. Первый пользователь
docker compose exec web python scripts/web_user.py add <имя>
```

Дальше Apache. Сначала временный сайт только под проверку домена:

```bash
sudo mkdir -p /var/www/certbot/.well-known/acme-challenge
# vhost с Alias на /var/www/certbot — см. первый блок в
# deploy/astrocalendar.optegra.ru.conf
sudo a2ensite astrocalendar && sudo systemctl reload apache2
```

Сертификат. Если системный certbot сломан (на этой машине он падает из-за
несовместимости pyOpenSSL), берём образ:

```bash
sudo docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d <домен> --non-interactive --agree-tos --keep-until-expiring
```

После этого кладём полный vhost и перезагружаем Apache:

```bash
sudo cp deploy/astrocalendar.optegra.ru.conf \
        /etc/apache2/sites-available/astrocalendar.conf
sudo apache2ctl configtest && sudo systemctl reload apache2
```

Продление — в `/etc/cron.d/astrocalendar-certbot`, дважды в сутки, с
перезагрузкой Apache только при фактическом обновлении сертификата.

---

## Обновление

```bash
ssh podcast '/data/astrocalendar/repo/deploy/update.sh'
```

Скрипт забирает код, пересобирает образ и перезапускает контейнер. Данные,
архив выпусков и пользователи лежат в томе и не затрагиваются.

---

## Особенность площадки: NumPy 1.x

Виртуальный процессор сервера (QEMU 2.5+) не поддерживает набор инструкций
x86-64-v2, с которым собраны колёса NumPy 2.x: контейнер падал при импорте
ещё до старта приложения. Поэтому в `requirements-web.txt` стоит `numpy<2` —
сборки 1.26 рассчитаны на SSE3 и работают. Если однажды сервер переедет на
процессор поновее, ограничение можно снять.

---

## Локальный запуск

```bash
pip install -r requirements-web.txt
python -c "import secrets; print('ASTROCAL_WEB_SECRET=' + secrets.token_urlsafe(48))" >> .env
python scripts/web_user.py add me
python scripts/serve_web.py --dev
```

Флаг `--dev` снимает требование HTTPS с сессионной куки, иначе браузер не
сохранит её на `http://localhost`.
