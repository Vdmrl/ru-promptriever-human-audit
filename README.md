# Argilla-аудит ru-Promptriever

Эта папка содержит отдельный вариант интерфейса для human audit из 'paper/REBUTTAL_MASTER_PLAN.md'. Сам интерфейс предоставляет Argilla, а репозиторий содержит Docker-конфигурацию, скрипты загрузки/выгрузки и публичную ослеплённую выборку.

## Инструкция для Даши

### Что нужно установить

Нужен только:

1. Docker Desktop: https://www.docker.com/products/docker-desktop/
2. Git: https://git-scm.com/downloads

После установки Docker Desktop должен быть запущен. Проверка в PowerShell:

~~~powershell
docker --version
docker compose version
~~~

### Первый запуск

Склонируй репозиторий и перейди в эту папку:

~~~powershell
git clone <ССЫЛКА_НА_РЕПОЗИТОРИЙ>
cd ru-promptriever\human_annotation\argilla
~~~

По умолчанию для всех пользователей (администратора `argilla`, разметчиков `daria` и `vladimir`) установлен пароль **`password`**. 

При желании изменить пароли, создайте файл `.env` рядом с `docker-compose.yml` и задайте свои значения:

~~~dotenv
ARGILLA_OWNER_PASSWORD=new-owner-password
ARGILLA_DARIA_PASSWORD=new-daria-password
ARGILLA_VLADIMIR_PASSWORD=new-vladimir-password
~~~

Затем запустите Argilla:

~~~powershell
docker compose up -d --build
~~~

Подождите примерно минуту и откройте в браузере:

http://localhost:6900

Сначала выполните настройку датасета:

~~~powershell
docker compose run --rm tools python scripts/setup_argilla.py
~~~

После этого войдите в интерфейс под своим пользователем:

- username: `daria` или `vladimir`
- password: `password` (или значение из `.env`, если вы его переопределили)

### Что именно размечать

В каждом примере будут показаны:

- query из итоговой записи датасета;
- положительный passage из итоговой записи;
- query для финальной пары;
- instruction;
- четыре документа в случайном порядке.

Для каждого примера нужно ответить на шесть обязательных вопросов.

1. Query написан на понятном и приемлемом русском языке — 'Да'/'Нет'.
2. Положительный passage написан на понятном, связном русском языке — 'Да'/'Нет'.
3. Для каждого из четырёх документов выбрать ровно один вариант:
   - '1' — документ не отвечает на query;
   - '2' — документ отвечает на query, но нарушает instruction;
   - '3' — документ отвечает на query и удовлетворяет instruction.

Отдельно определять positive и negatives не нужно: порядок документов специально перемешан. Не пытайся угадать исходные роли документов и не ищи правильный ответ по порядку.

Для бинарных вопросов ставь 'Да', если текст понятен и пригоден для использования, даже если есть небольшие стилистические шероховатости. Ставь 'Нет', если есть явная грамматическая, лексическая, языковая или логическая проблема, которая мешает понять текст.

Варианта 'неясно' нет. Если пример кажется спорным, выбери наиболее обоснованный вариант. Такие случаи будут учитываться через расхождения между двумя разметчиками.

Не нужно:

- оценивать исходный машинный перевод;
- проверять сохранение смысла относительно исходного документа;
- оценивать instruction отдельным вопросом;
- ставить оценки от 1 до 5;
- писать комментарии или объяснения.

Если не закончишь пример за один раз, сначала нажми в Argilla кнопку `Save as Draft`, а затем закрой браузер или выполни 'docker compose stop'. После сохранения draft ответы не пропадут. Для продолжения снова выполни:

~~~powershell
docker compose start
~~~

и открой http://localhost:6900. В очереди останутся незавершённые записи.

### Как передать результаты

Когда закончишь всю разметку, выполни:

~~~powershell
docker compose run --rm tools python scripts/export_annotations.py --output-dir data/exports
~~~

Появится файл:

~~~text
data/exports/annotations.jsonl
~~~

Пришли этот файл Владимиру. Он содержит твои ответы и идентификаторы примеров, но не содержит правильных ролей документов.

Не присылай Docker volumes и не добавляй в GitHub '.env': для подсчёта метрик нужен только 'annotations.jsonl'.

## Инструкция для Владимира: подготовка выборки

Выборка уже должна быть подготовлена Владимиром из итогового parquet-датасета: 60 train и 40 synthetic-test строк, без repeated queries и ровно с тремя `new_negatives` в каждой строке. Даше не нужно запускать этот шаг.

Пример:

~~~powershell
python human_annotation/argilla/scripts/prepare_from_final_dataset.py --dataset-dir data_preprocessing/data/output_final_dataset/data --out-dir human_annotation/argilla/data
~~~

Для передачи Даше нужен только:

~~~text
human_annotation/
  argilla/
    docker-compose.yml
    Dockerfile.tools
    requirements.txt
    README.md
    scripts/setup_argilla.py
    scripts/export_annotations.py
    data/public_items.jsonl
    data/sample_metadata.json
~~~

Файл 'data/private_manifest.jsonl' нельзя передавать разметчику: в нём хранятся роли документов и split. Он нужен только для последующего анализа.

## Что делает код

- 'scripts/setup_argilla.py' создаёт пользователей, датасет, поля, вопросы и загружает records;
- 'scripts/export_annotations.py' выгружает все ответы с Argilla в JSONL и CSV;
- 'scripts/prepare_from_final_dataset.py' создаёт выборку непосредственно из итоговых train/test parquet и приватное сопоставление ролей;
- 'scripts/prepare_argilla_sample.py' оставлен для случая, когда доступны исходные generation records;
- 'docker-compose.yml' запускает Argilla, PostgreSQL, Elasticsearch, Redis и контейнер с Python SDK.

Argilla хранит конфигурацию и ответы в persistent Docker volumes. Передача результатов выполняется через экспорт, а не через копирование volumes.
