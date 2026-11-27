# Локальный replay и адаптация кластеров

Команды читают сохранённый корпус и моделируют изменение состояния локально.
Без флага `--with-model` запускаются только локальные контроллеры. Рабочий корпус, результаты и параметры установки храните под `.local-data/`.

```powershell
python -m kolos_states.cluster_replay --frozen-corpus .local-data/corpus.json --output .local-data/runs/replay
python -m kolos_states.cluster_adaptation --corpus .local-data/corpus.json --output .local-data/runs/adaptation
```

Для повторения прежнего выбора укажите `--teaching-product-id` или заполните поле `teaching_product_id` в локальном `.local-data/cluster-replay.json`. Без указанного товара выбирается первый сохранённый пример восстановления. Если указанный товар не подходит, команда останавливается.

В том же локальном файле можно задать `source` (путь к исходному журналу), `corpus` (путь к сохранённому корпусу) и `hermes_install` (путь к библиотеке для явного `--with-model`). Аргументы командной строки имеют приоритет. Относительные пути в JSON отсчитываются от каталога файла.

Проверка на искусственных входах: `python -m unittest tests.desktop.test_cluster_replay tests.desktop.test_cluster_adaptation`.
