# ShortForm-Bench

ShortForm-Bench measures whether AI models can write short-form video scripts that creators would actually film.

25 creators on TikTok and Instagram, five in each of five niches, each have ten video pitches. Every model gets the creator's channel description, ten of their past scripts and one pitch, researches the topic on the web, and writes the script. The creator then reads every model's script blind and decides whether they would film it.

This repository holds the code that generates the scripts, the exact prompt, and three example tasks.

## What is here

| Path | What it is |
|---|---|
| `PROTOCOL.md` | The methodology: tasks, rating, scoring and limitations |
| `harness/` | The generation harness. `harness/README.md` explains how it works and every rule it follows |
| `harness/prompt.py` | The prompt every model receives, word for word, and the parser for the reply |
| `harness/tools.py` | The two tools every model gets: web search and page fetch |
| `harness/config.json` | The models tested, their settings and the limits |
| `examples/tasks/` | Three real tasks, one each from finance, fitness and technology |
| `examples/prompts/` | The full prompt a model receives for each example task |
| `examples/scripts/` | The script each of the seven models wrote for each example task |

## Run it

The harness is plain Python 3.10 or later with nothing to install.

Print the prompt for a task:

```bash
python3 -m harness prompt example-tech-01
```

Generate scripts. Models are called through [OpenRouter](https://openrouter.ai), so this needs `OPENROUTER_API_KEY`, and a `TAVILY_API_KEY` for web search:

```bash
python3 -m harness run --round demo --tasks example-tech-01
```

Read what came back:

```bash
python3 -m harness viewer --round demo
```

Run the tests, which need no network or keys:

```bash
python3 -m unittest harness.test_harness
```

## How a script is generated

1. The harness builds the prompt from the task.
2. The model can call `web_search` and `fetch_page`, up to 20 times. Both run in the harness, so every model searches the same index and reads pages through the same reader.
3. The model replies with a script, written one spoken line per line, and the pages it relied on.
4. The harness saves the script, every tool call, token counts, cost and timings.

Every model gets the same prompt, the same tools and the same settings. Each writes one script per task, and the script is never edited before a creator reads it.

## What is not here

The benchmark's 250 tasks, the scripts written for them and the creators' ratings are private, so that models can't be trained on them. The three tasks in `examples/` are published with the creators' permission, and the creators are not named.

## Licence

The code is under the MIT licence. The transcripts and scripts in `examples/` are included for illustration and remain the property of the creators; they are not covered by the licence.
