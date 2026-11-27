/** Test-world physics and independent demonstrations. Not imported by inference. */
export const SHARED_FIXTURE = {
  "schema": "kolos-shared-curriculum/1",
  "world": {
    "version": 0,
    "surface": "desk",
    "selected": "",
    "focus": "",
    "output": "",
    "cursor": {
      "x": 500,
      "y": 300
    },
    "effects": [],
    "surfaces": {
      "desk": {
        "label": "Общий рабочий стол",
        "field": null,
        "icons": [
          {
            "id": "A",
            "label": "A",
            "x": 200,
            "y": 170,
            "enter": "window"
          },
          {
            "id": "B",
            "label": "B",
            "x": 500,
            "y": 170
          },
          {
            "id": "CALC",
            "label": "CALC",
            "x": 780,
            "y": 170,
            "click": "calculator"
          },
          {
            "id": "TO_OLD",
            "label": "Архивная панель",
            "x": 200,
            "y": 420,
            "click": "old"
          },
          {
            "id": "TO_NEW",
            "label": "Новая панель",
            "x": 500,
            "y": 420,
            "click": "new"
          },
          {
            "id": "TO_LEVELS",
            "label": "Уровни",
            "x": 780,
            "y": 420,
            "click": "L0"
          }
        ]
      },
      "window": {
        "label": "Перекрывающее окно",
        "field": null,
        "icons": [
          {
            "id": "X",
            "label": "X",
            "x": 920,
            "y": 75,
            "click": "desk"
          },
          {
            "id": "D",
            "label": "D",
            "x": 260,
            "y": 260
          },
          {
            "id": "E",
            "label": "E",
            "x": 630,
            "y": 260
          }
        ]
      },
      "calculator": {
        "label": "Поле калькулятора",
        "field": "FIELD",
        "icons": [
          {
            "id": "X",
            "label": "X",
            "x": 920,
            "y": 75,
            "click": "desk"
          },
          {
            "id": "DIGITS",
            "label": "DIGITS",
            "x": 250,
            "y": 240
          },
          {
            "id": "RESULT",
            "label": "RESULT",
            "x": 660,
            "y": 240
          }
        ]
      },
      "old": {
        "label": "Архивная панель · слабый прямой путь",
        "field": null,
        "icons": [
          {
            "id": "FAST",
            "label": "FAST",
            "x": 240,
            "y": 170,
            "click": "target"
          },
          {
            "id": "VIA",
            "label": "VIA",
            "x": 700,
            "y": 170,
            "click": "middle"
          },
          {
            "id": "ARCHIVE",
            "label": "Архивная версия",
            "x": 480,
            "y": 390
          }
        ]
      },
      "new": {
        "label": "Новая панель · сильный прямой путь",
        "field": null,
        "icons": [
          {
            "id": "FAST",
            "label": "FAST",
            "x": 240,
            "y": 170,
            "click": "target"
          },
          {
            "id": "VIA",
            "label": "VIA",
            "x": 700,
            "y": 170,
            "click": "middle"
          },
          {
            "id": "CURRENT",
            "label": "Текущая версия",
            "x": 480,
            "y": 390
          }
        ]
      },
      "middle": {
        "label": "Общий обход",
        "field": null,
        "icons": [
          {
            "id": "NEXT",
            "label": "NEXT",
            "x": 480,
            "y": 160,
            "click": "target"
          }
        ]
      },
      "target": {
        "label": "Общий результат двух маршрутов",
        "field": null,
        "icons": [
          {
            "id": "TARGET",
            "label": "TARGET",
            "x": 500,
            "y": 300
          },
          {
            "id": "HOME",
            "label": "HOME",
            "x": 180,
            "y": 100,
            "click": "desk"
          }
        ]
      },
      "trap": {
        "label": "Неожиданный исход",
        "field": null,
        "icons": [
          {
            "id": "RETURN",
            "label": "RETURN",
            "x": 450,
            "y": 170,
            "click": "new"
          }
        ]
      },
      "L0": {
        "label": "Уровень 0",
        "field": null,
        "icons": [
          {
            "id": "GO0",
            "label": "GO0",
            "x": 300,
            "y": 150,
            "click": "L1"
          }
        ]
      },
      "L1": {
        "label": "Уровень 1",
        "field": null,
        "icons": [
          {
            "id": "GO1",
            "label": "GO1",
            "x": 400,
            "y": 150,
            "click": "L2"
          }
        ]
      },
      "L2": {
        "label": "Уровень 2",
        "field": null,
        "icons": [
          {
            "id": "GO2",
            "label": "GO2",
            "x": 500,
            "y": 150,
            "click": "L3"
          }
        ]
      },
      "L3": {
        "label": "Уровень 3",
        "field": null,
        "icons": [
          {
            "id": "DONE",
            "label": "DONE",
            "x": 600,
            "y": 150
          },
          {
            "id": "HOME",
            "label": "HOME",
            "x": 180,
            "y": 100,
            "click": "desk"
          }
        ]
      }
    }
  },
  "exposure": "5432",
  "episodes": [
    {
      "surface": "desk",
      "query": "открой окно",
      "object": "A",
      "enter": true
    },
    {
      "surface": "window",
      "query": "закрой окно",
      "object": "X"
    },
    {
      "surface": "desk",
      "query": "добавь траты 1700",
      "object": "CALC",
      "keys": "1700"
    },
    {
      "surface": "calculator",
      "query": "верни рабочий стол",
      "object": "X"
    },
    {
      "surface": "desk",
      "query": "открой архивную панель",
      "object": "TO_OLD"
    },
    {
      "surface": "desk",
      "query": "открой новую панель",
      "object": "TO_NEW"
    },
    {
      "surface": "desk",
      "query": "открой уровни",
      "object": "TO_LEVELS"
    },
    {
      "surface": "old",
      "query": "архивный прямой переход",
      "object": "FAST",
      "weight": 0.35
    },
    {
      "surface": "old",
      "query": "архивный обход",
      "object": "VIA"
    },
    {
      "surface": "new",
      "query": "новый прямой переход",
      "object": "FAST"
    },
    {
      "surface": "new",
      "query": "новый обход",
      "object": "VIA"
    },
    {
      "surface": "middle",
      "query": "пройти общий обход",
      "object": "NEXT"
    },
    {
      "surface": "trap",
      "query": "вернуться из неожиданного окна",
      "object": "RETURN"
    },
    {
      "surface": "target",
      "query": "вернуться с результата",
      "object": "HOME"
    },
    {
      "surface": "L0",
      "query": "пройти переход 0",
      "object": "GO0"
    },
    {
      "surface": "L1",
      "query": "пройти переход 1",
      "object": "GO1"
    },
    {
      "surface": "L2",
      "query": "пройти переход 2",
      "object": "GO2"
    },
    {
      "surface": "L3",
      "query": "вернуться с уровней",
      "object": "HOME"
    }
  ],
  "language": [
    {
      "phrase": "я хочу увидеть 1700 в поле",
      "goal": {
        "kind": "field",
        "focus": "FIELD",
        "value": "1700"
      }
    },
    {
      "phrase": "я хочу увидеть 2345 в поле",
      "goal": {
        "kind": "field",
        "focus": "FIELD",
        "value": "2345"
      }
    },
    {
      "phrase": "пусть в поле будет 1700",
      "goal": {
        "kind": "field",
        "focus": "FIELD",
        "value": "1700"
      }
    },
    {
      "phrase": "пусть в поле будет 2345",
      "goal": {
        "kind": "field",
        "focus": "FIELD",
        "value": "2345"
      }
    },
    {
      "phrase": "сделай в поле 1700 пожалуйста",
      "goal": {
        "kind": "field",
        "focus": "FIELD",
        "value": "1700"
      }
    },
    {
      "phrase": "сделай в поле 2345 пожалуйста",
      "goal": {
        "kind": "field",
        "focus": "FIELD",
        "value": "2345"
      }
    }
  ]
};
