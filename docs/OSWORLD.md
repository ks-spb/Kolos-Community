# Автономный прогон Колоса на OSWorld

Стенд запускает десять заданий оригинального OSWorld из [манифеста выборки](../kolos_states/osworld/manifest.py). Каждое задание запускается с пустым и обученным снимком памяти. GPT, Claude и подсказки человека во время зачёта не используются. Оценку выставляет штатный `DesktopEnv.evaluate()` по итоговому состоянию гостевой Ubuntu.

## Установка в WSL2

В Linux-окружении проекта нужны Python 3.12, работающий Docker, Git и официальный Ubuntu `Ubuntu.qcow2`. Для сборки зависимостей из исходников нужны компилятор C/C++, заголовки Python и Linux. Выделите место под архив размером 12,3 ГБ, распакованный образ и зависимости. Если `/dev/kvm` отсутствует, Docker запускает гостя через программную эмуляцию. [Подготовка Docker для OSWorld](https://github.com/xlang-ai/OSWorld/blob/desktop-env-v1.0.3/desktop_env/providers/docker/DOCKER_GUIDELINE.md)

```bash
mkdir -p .tmp/osworld-vm
git clone --branch desktop-env-v1.0.3 --depth 1 https://github.com/xlang-ai/OSWorld.git .tmp/osworld-upstream
uv venv .tmp/osworld-venv
uv pip install --python .tmp/osworld-venv/bin/python --index https://download.pytorch.org/whl/cpu 'torch==2.5.1+cpu' 'torchvision==0.20.1+cpu'
uv pip install --python .tmp/osworld-venv/bin/python desktop-env==1.0.3 'numpy==1.26.4'
docker pull happysixd/osworld-docker@sha256:0e6497a9295647cf05bf2b2af522fdd79bdeba2737595259cab310a3bcf6baa9
docker tag happysixd/osworld-docker@sha256:0e6497a9295647cf05bf2b2af522fdd79bdeba2737595259cab310a3bcf6baa9 happysixd/osworld-docker:latest
curl -fL -C - -o .tmp/osworld-vm/Ubuntu.qcow2.zip https://huggingface.co/datasets/xlangai/ubuntu_osworld/resolve/a5d9c3eaae98eebf6e3a0beb84e7e47cf72ae133/Ubuntu.qcow2.zip
echo 'b795b6cd4c69b252c1b4f10150a347795555032501b60fd031751ed09b896712  .tmp/osworld-vm/Ubuntu.qcow2.zip' | sha256sum --check
python3 -m zipfile -e .tmp/osworld-vm/Ubuntu.qcow2.zip .tmp/osworld-vm
```

Для зачёта используется коммит источников `9d6f711d234b84cbff1b5199211610baa03b000c`. Команда проверяет чистоту checkout, версию библиотеки, digest Docker и записывает SHA-256 гостевого диска. Образ монтируется в режиме чтения. Гостю выделяются 4 ГБ памяти и три виртуальных процессора в обоих режимах. При программной эмуляции API может загрузиться раньше GNOME. Стенд увеличивает таймаут запуска GNOME до 10 минут в одноразовом слое гостя, проверяет оконный менеджер и убеждается, что кадр содержит рабочий стол. Перед началом убедитесь, что переменная `OSWORLD_VM_SECRET_MOUNTS` пуста. [Релиз desktop-env 1.0.3](https://github.com/xlang-ai/OSWorld/releases/tag/desktop-env-v1.0.3)

## Запуск

```bash
bench() {
  .tmp/osworld-venv/bin/python -B -m kolos_states.osworld "$@" \
    --osworld .tmp/osworld-upstream \
    --vm-image .tmp/osworld-vm/Ubuntu.qcow2 \
    --output tests/desktop-output/osworld
}
bench all --fast-reset
```

`all` выполняет перечисленные ниже этапы в одной сессии. Их также можно запускать по одному. Параметр `--fast-reset` сокращает ожидание при программной эмуляции. Стенд проверяет откат снимка QEMU на отдельном временном файле до подготовки заданий. Если проверка или восстановление не проходят, среда возвращается к штатному перезапуску Docker. Способ восстановления записывается для каждой оценённой попытки. Параметр `--video-adapter std` выбирает стандартный VGA QEMU. Выбранный адаптер записывается в отчёте вместе с настройками гостя.

- `preflight` проверяет три группы приложений и калибрует судью на отдельном официальном задании.
- `teach` проводит 12 синтетических показов и три контрольных упражнения. `teaching.json` содержит число усвоенных показов, проверку контрольных результатов и отпечатки памяти. Код выхода 1 означает, что часть показов или контролей не прошла.
- `run` использует два замороженных снимка из `teach` и записывает `results.json` после каждой попытки. Повторный запуск с теми же снимками подхватывает уже полученные оценки. В отчёте отражаются качество обучения, балл каждого задания, время и причина остановки. Технический сбой записывается отдельно от оценки 0. На попытку отводится до 50 действий или 300 секунд после подготовки задачи.

Разбор инструкций ограничен десятью семействами целей. Параметры берутся из текста и интерфейса. Прогон измеряет перенос выученных переходов на конкретной десятке. Для сравнения с опубликованными результатами всего OSWorld потребуется их набор и протокол.
