# Журнал навчальних подань

POST /submissions реєструє синтетичне подання з `group_code` на кшталт SE-17 та унікальним `submission_key`. Код групи має відповідати SE- і двом цифрам. За неправильним форматом API відповідає 400. GET /submissions/<id> читає подання, а повторний POST повертає 200 з наявним номером. Якщо той самий ключ подано з іншою групою, API відповідає 409.

Випуск v1.1.0 повертає 201 після запису. У v2.1.0 після коміту формується короткий код підтвердження. Режим `offline` вимикає підтвердження, тому POST дає 503 з номером збереженого подання. /health залишається доступним.

## Від перевірки до образу

Для локального запуску потрібні Python 3.12+, Docker з Linux-контейнерами та curl. Образи релізів призначені для Linux ARM64.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
python lab.py test --timeout 45
```

`lab.py test` запускає pytest через subprocess. Якщо pytest падає, цей статус повертається конвеєру. Якщо час вичерпано, команда повертає 124. Крок **Validate responses and data** використовує Bash із pipefail. У контрольній гілці очікуваний код /health змінено на 202 замість 200. Крок **Build release image** пропускається, але діагностика pytest зберігається.

| Доказ | Запуск |
| --- | --- |
| Перевірки та образ v1.1.0 | [GitHub Actions](https://github.com/mag871498-sys/submission-journal-ci/actions/runs/45611217021) |
| Перевірки та образ v2.1.0 | [GitHub Actions](https://github.com/mag871498-sys/submission-journal-ci/actions/runs/45611282064) |
| Зупинка збірки через помилку тесту | [Журнал завдання](https://github.com/mag871498-sys/submission-journal-ci/actions/runs/45611287294/job/139195170072) |

Маючи архіви в `local-artifacts/v1` і `local-artifacts/v2`, переходь до staging. Для чистої копії репозиторію завантаж їх із [GitHub Releases](https://github.com/mag871498-sys/submission-journal-ci/releases) або з артефактів Actions:

```bash
gh run download 45611217021 -n image-v1.1.0 -D local-artifacts/v1
gh run download 45611282064 -n image-v2.1.0 -D local-artifacts/v2
```

Скрипт доставки перевіряє SHA-256 і Docker Image ID. Конвеєр також зберігає компактний набір без байт-ідентичних шарів базового образу. Перед розгортанням повний архів має збігатися з оригіналом із CI за SHA-256.

## Приймання на тестовому стенді

```bash
for version in v1 v2; do
  bash scripts/deliver.sh "local-artifacts/$version" staging
  stage=$(docker compose -p journal-stage ps -q stage)
  python -m pytest -q --hosts="docker://$stage" infra
  curl -fsSi --max-time 4 -H 'Content-Type: application/json' \
    -d "{\"group_code\":\"SE-17\",\"submission_key\":\"stage-$version-$(date +%s)\"}" \
    http://127.0.0.1:8291/submissions
done
```

Staging використовує свій том і режим `normal`. Перевір, що обидва запити повертають 201. Після приймання v2 впевнися, що відповідь містить `confirmation`. Робочі v1 та v2 використовують спільний постійний том SQLite.

## Контроль 10% трафіку

У кожній серії 200 POST із синтетичними даними й новими ключами. Скрипт використовує тайм-аут 2 с і паузу 40 мс між спробами. У змішаній серії v2 отримує кожен десятий запит. Оператор дозволяє розширення після щонайменше 20 спроб на v2, якщо до 5% завершилися 5xx або без відповіді та p95 серед отриманих відповідей не перевищує 180 мс. SLO — щонайменше 99% спроб у всій серії мають повернути 201 до 1 с включно.

```bash
prefix="journal-$(date +%s)"
out="results/$prefix"
bash scripts/deliver.sh local-artifacts/v1 working
docker compose -p journal-work up -d prometheus
python scripts/traffic.py baseline --prefix "$prefix" --output "$out"

LAB_CONFIRM_MODE=offline bash scripts/deliver.sh local-artifacts/v2 working
python scripts/traffic.py canary --prefix "$prefix" --output "$out" &
traffic=$!
sleep 2
docker stats --no-stream $(docker compose -p journal-work ps -q v1 v2)
wait "$traffic"
sleep 2
python scripts/metrics.py --output "$out/canary-prometheus.json"
docker compose -p journal-work logs --no-log-prefix v1 v2 | awk '/^[{]/' > "$out/canary.jsonl"
```

За перевищення порога оператор припиняє маршрутизацію на v2, зупиняє її контейнер і повторює замір на v1:

```bash
docker compose -p journal-work stop v2
python scripts/traffic.py rollback --prefix "$prefix" --output "$out"
docker compose -p journal-work logs --no-log-prefix v1 v2 | awk '/^[{]/' > "$out/submissions.jsonl"
python lab.py summarize "$out/submissions.jsonl"
python lab.py summarize "$out/missing.jsonl"
```

У `canary.csv` знайди номер, ключ та request_id будь-якого подання v2 зі статусом 503. У JSONL за request_id знайди записи `submission_saved`, `confirmation_failed` і `submission_response`. Лічильник CLI враховує лише останню подію. Перевір GET з номером і POST з тим самим ключем на порті 8281:

```bash
curl -fsSi --max-time 4 http://127.0.0.1:8281/submissions/270
curl -fsSi --max-time 4 -H 'Content-Type: application/json' \
  -d '{"group_code":"SE-17","submission_key":"journal-2511-canary-070"}' \
  http://127.0.0.1:8281/submissions
```

У цих двох командах наведені номер і ключ зі збереженого експерименту. Під час повторення підстав значення з нового CSV. При завершенні роботи зупини стенди без видалення томів:

```bash
docker compose -p journal-work --profile working down
docker compose -p journal-stage --profile staging down
```

Виміри трьох серій, результат Prometheus і підтвердження відкату збережені в [evidence](evidence/).

## Підготовка матеріалів

ШІ допоміг написати чернетку сервісу, перевірок і звіту. Код та висновки звірено з реальними виконаннями pytest, Testinfra, GitHub Actions і HTTP-запитами під час експерименту.
