# Example tasks

Three real tasks from the benchmark, with what each model wrote for them. They are published with the creators' permission. The creators are not named, and video ids have been replaced.

## A task file

`tasks/example-tech.json` and its two neighbours. One file per creator:

| Field | What it is |
|---|---|
| `creator_id` | A label for the creator. Never shown to the model |
| `niche` | One of the five niches |
| `channel_description` | Up to 150 words, in the creator's voice, on who watches, what the channel covers and how they sound |
| `past_scripts` | Ten of the creator's published videos: `duration_s` is the video's length, `transcript` is what was said, transcribed automatically from the audio |
| `pace_words_per_second` | The creator's speaking pace across those ten videos. Used to estimate how long a script would run. Not shown to the model |
| `pitches` | The video ideas. Each has a `task_id`, a `title`, a `topic` of one or two sentences, and `target_length_seconds` as a low and high bound |
| `content_sha` | A fingerprint of everything the model is shown, used to detect changes |

In the benchmark each creator has ten pitches. Each example file carries one.

## A prompt

`prompts/` has the full prompt for each example task, exactly as a model receives it: the system prompt, then the task message. Regenerate one with `python3 -m harness prompt example-tech-01`.

## A script record

`scripts/<task id>/<model>.json`. One file per model per task:

| Field | What it is |
|---|---|
| `model`, `model_settings` | The model and the settings it ran with |
| `script` | The script exactly as the model wrote it |
| `lines` | The same script as a list, one spoken line per entry |
| `length` | Words, lines, words per line, the estimated spoken length in seconds, and whether that falls inside the target |
| `sources` | Each page the model said it relied on, what it said the page supports, and whether the model actually opened that page during the run |
| `tool_calls` | Every search and page request, in order |
| `usage`, `seconds_taken` | Tokens, cost in US dollars, and wall-clock time |
| `format_flags` | Anything in the script that isn't spoken words, such as headings or stage directions. Empty when clean |

The full conversation and the saved copies of web pages are left out of these records.

`scripts.md` has the same scripts in one readable file.
