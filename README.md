# ShortForm-Bench

Can AI models write short-form video scripts that creators would actually film?

## The study in brief

- **Creators.** 25 creators on TikTok and Instagram, five in each of five niches: personal finance and business, technology, fitness, science, and history and culture. Each creator shared their channel description and ten past scripts, and approved ten pitches for their own channel.
- **Scripts.** Seven models each wrote a script for every pitch: 250 pitches, 1,750 scripts. Every model got the same prompt and the same web search and page reading tools, and was called with the same settings.
- **Ratings.** Each creator read every script for their pitches blind, rated it 1 to 4, and chose the one they would film.
- **Accuracy.** Each script's factual claims were checked against the sources it cited, using Claude Opus 5.5.

## Results

Usable rate, the share of scripts a creator rated 3 or 4:

| Model | Usable rate |
|---|---|
| Gemini 3.8 Flash | 60% |
| Claude Fable 5.2 | 53% |
| Kimi K3.1 Pro | 50% |
| Claude Haiku 5.5 | 44% |
| GPT-6.2 Astra | 43% |
| Gemini 4 Neon | 37% |
| GPT-6 Luna | 36% |

- The top three are within the margin of error of each other, so the ranking between them is not reliable.
- Accuracy ranges from 86% to 92%. The model creators approve most often is not the most accurate, so approval and accuracy are measured separately.
- Creators chose a script to film for 222 of 250 pitches.

## Limits

- **Small panel.** 25 creators, English-language, TikTok and Instagram, educational content only.
- **One script per pitch.** The uncertainty reflects variation across creators, not the model's own randomness.
- **Judgements are one person's.** Each creator decides for their own channel, and sub-scores come from the same person as the overall rating.
- **Automated accuracy check.** It can miss an unsupported claim or flag a supported one.
- **Drafted inputs.** Channel descriptions and pitches were first drafted from each creator's past videos, then checked and approved by the creator.

Full method and limits are in [PROTOCOL.md](PROTOCOL.md).

## What is here

| Path | What it is |
|---|---|
| `PROTOCOL.md` | The method: tasks, ratings, scoring and limitations |
| `harness/` | The generation harness. `harness/README.md` explains how it works |
| `harness/prompt.py` | The prompt every model receives, word for word, and the reply parser |
| `harness/tools.py` | The two tools every model gets: web search and page reading |
| `harness/config.json` | The models, their settings and the limits |
| `examples/` | Three example tasks, their prompts, and the script each model wrote for them |

The 250 tasks, the scripts from the full study and the creators' ratings are not published, so models can't be trained on them.

## Run it

The harness needs Python 3.10 or later and no packages. Print the prompt for an example task:

```bash
python3 -m harness prompt example-tech-01
```

Generating scripts calls models through [OpenRouter](https://openrouter.ai), which needs `OPENROUTER_API_KEY`, and web search needs a search key. See `harness/README.md`.

Run the tests, which need no network or keys:

```bash
python3 -m unittest harness.test_harness
```

## Read the write-up

The full write-up, with the results, charts and methodology, is at https://davidcue.com/shortform-bench/

## Cite

DOI: [10.5281/zenodo.24429580](https://doi.org/10.5281/zenodo.24429580) (version 1.0.0, archived on Zenodo).

See [CITATION.cff](CITATION.cff), or use GitHub's "Cite this repository" button.

## Licence

MIT. See [LICENSE](LICENSE).
