# Generation harness

The harness is the program that gets a script out of each model. For one task and one model it sends the prompt, lets the model search and read the web, and saves the script it writes along with everything that happened on the way.

It is plain Python with nothing to install: it uses only the standard library.

## How one script gets made

1. The harness builds the prompt from the task: channel description, ten past scripts, the pitch and its target length.
2. It sends the prompt to the model, along with the definitions of two tools: `web_search` and `fetch_page`.
3. The model replies either with tool requests or with its final answer.
4. For each tool request, the harness runs the search or opens the page, saves what came back, and sends the result to the model. Then it goes back to step 3.
5. After 20 tool calls the tools are switched off and the model has to write.
6. The harness pulls the script and the source list out of the final reply and saves one record for the run.

The script comes back written line by line: one spoken line on each line of text.

## Files

| File | What it does |
|---|---|
| `config.json` | The models and their settings, limits, search provider, spending cap |
| `tasks.py` | Loads task files and checks them against a lock |
| `prompt.py` | The prompt, and the parser for the model's reply |
| `tools.py` | Search, page reading, and the saved copies |
| `models.py` | Sends requests to OpenRouter |
| `run.py` | The loop in the six steps above, and the run record |
| `viewer.py` | Builds a one-file page for reading a round: pick a pitch, switch between models |
| `__main__.py` | Commands |
| `test_harness.py` | Tests that run without the network |

## Methodology

**One prompt for every model.** The prompt is plain: who the script is for, what the model is given, the rules for the script, and the reply format. It carries no writing advice and is not tuned for any model. Print it with `python3 -m harness prompt <task id>`.

**Scripts are written line by line.** The prompt asks for one spoken line on each line of text, each a single beat said in one breath, with no paragraphs, blank lines, bullets or numbering. That is how short-form creators write scripts, and it lets them judge pacing line by line. The record keeps the number of lines, the average words per line and the longest line.

**What the model sees.** The channel description, ten past videos as transcripts with their lengths in seconds, and the pitch title, topic and target length.

**What it does not see.** The creator's name, links, captions and view counts, so it can't look the creator up.

**Past scripts.** Ten of the creator's recent videos. They are machine transcripts of the audio, and the prompt says so.

**Tasks are locked.** Once creators have approved their tasks, a fingerprint of each creator's tasks is stored, and the harness refuses to run if any task no longer matches it.

**Tools run in the harness.** Models' own built-in web search is never switched on. Every model searches the same index and reads pages through the same reader. Otherwise the benchmark would partly rank search products.

**Same answer for the same question.** Within a round, the first successful result for a search query or a page is saved and reused. Two models that run the same search get identical results. Failures are not saved, so a page that timed out once is tried again.

**20 tool calls.** Each search or page request counts as one, including failed ones. On the 20th the model is told it has no calls left, and the tools are switched off for its next reply. Requests past the limit are refused, not run.

**One script per model per task.** There is no second attempt and no picking the best of several. Requests are retried only when the service fails (rate limits, server errors, timeouts), never because of what a model wrote.

**One format reminder.** If the final reply has no script block, the harness sends one fixed message asking for the same script in the right format. If there is still none, the run is saved as `no_script`.

**Every model runs at "high" thinking.** `config.json` sets it for each model, and results name the setting beside the model. No temperature is set. The output limit is 40,000 tokens. All settings are saved with the run.

**Length is given in seconds.** The model is not told a word count. The harness estimates spoken length from the creator's own pace (words per second across their ten past videos). The estimate is for diagnosis; the creator's judgment is what counts.

**Sources.** The model lists each page it relied on and which facts it supports. The harness records whether each listed page was actually opened in that run and links it to the saved copy.

**The script is never edited.** What the model wrote is what the creator reads. Signs of non-spoken content (headings, stage directions, emoji) and of a script not written line by line (paragraphs, blank lines, bullets) are flagged in the record but not removed.

**Everything is saved.** Each run record holds the full conversation, every tool call, token counts, cost, timings, the prompt version and the settings.

**Privacy.** Requests are limited to providers that don't train on the data.

**Safety.** The model chooses which URLs to open, so the page reader refuses addresses on the local machine or network.

## Model access and search

Every model is called through OpenRouter, which gives one request format for every vendor's models. That keeps the harness to a single code path with no model getting special handling.

Search goes through one provider for every model. `config.json` names it: `tavily` needs a `TAVILY_API_KEY`. Pages are downloaded and stripped to text by the harness itself, and the search provider's page reader is tried when a site refuses.

## Known limits

- **PDFs can't be read**, and a few sites refuse both page readers.
- **Pages are cut at 20,000 characters**, and menus sometimes survive the clean-up. Every model gets the same text.
- **The web changes.** Models research live, so a rerun later will not find the same pages.

## Commands

```bash
python3 -m harness prompt example-tech-01
```

```bash
python3 -m harness run --round demo --tasks example-tech-01
```

```bash
python3 -m harness status --round demo
```

```bash
python3 -m harness show anthropic/claude-haiku-5.5 example-tech-01 --round demo
```

```bash
python3 -m harness viewer --round demo
```

```bash
python3 -m unittest harness.test_harness
```

`run` uses the models in `config.json`; `--models` picks others by their OpenRouter id. A run stops when the round reaches `budget_usd` in `config.json`. Finished scripts are skipped on a rerun, so an interrupted round can be resumed.

Generated scripts and saved pages go to `harness/data/`, which is not tracked.
