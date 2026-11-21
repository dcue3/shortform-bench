# ShortForm-Bench

ShortForm-Bench measures whether AI models can write short-form video scripts that creators actually film. Each model writes scripts for real creators' channels, and the creators decide whether to shoot them.

Version 1.1, 2026-11-21.

## Background

Shortform content writing is uniquely difficult for modern AI. 

Creators want to give a short video description and have an agent retrieve relevant information and draft a script matching their delivery and content style. 

As AI tends to the mean for writing, this benchmarks aims to evaluate frontier models on their ability to write genuinely usable and factually accurate scripts for creators. 

A script is only good if the creator would actually use it. An LLM judge can't decide that. So the judge here is the creator, and the test is whether they would film the script and post it on their own channel.

The benchmark covers educational content: explainers, lists and advice. It is structured enough to judge as text, and its claims can be checked against sources.

## Methodology

25 creators take part, five in each of five niches: personal finance/business, technology, fitness, science, and history/culture. Each creator has 10 pitches, which gives 250 tasks.

A task is one creator plus one pitch:

| Part | What it is |
|---|---|
| Channel description | Up to 150 words on who watches, what the channel covers and how the creator sounds |
| Past scripts | 10 of the creator's published videos, as transcripts |
| Pitch | One or two sentences on a video the creator hasn't made, with a target length |
| Tools | Web search and page fetch, the same for every model |
| Output | A script of spoken lines only, written line by line and sized to the target length, plus the sources it used |

Each pitch is a video idea the creator approved for their own channel and agreed to film.

Every model gets the same prompt and the same tools, with up to 20 tool calls per script. Each model writes one script per task.

Scripts are written the way short-form creators write them: one spoken line on each line of text, each a single beat said in one breath. There are no paragraphs.

The creator then reads every script written for their pitches. Scripts are unlabelled and in random order, so the creator doesn't know which model wrote which. They rate each script in two steps.

**Overall rating.** Would I film this?

| Rating | Meaning |
|---|---|
| 4. Film as is | I would film this as written. |
| 3. Small edits | I would film it after a few quick fixes. Fixing it is faster than writing it myself. |
| 2. Heavy rewrite | There is something usable, but I would rewrite most of it. |
| 1. Reject | I would not use any of it. |

A script rated 3 or 4 is **usable**.

**Sub-scores.** The creator also scores every script from 1 (poor) to 4 (excellent) on five things:

| Sub-score | The question |
|---|---|
| Voice | Does it sound like me, said the way I would say it? |
| Hook | Would the first lines stop someone scrolling? |
| Substance | Is the content specific, interesting and correct as far as I can tell? |
| Pacing | Read line by line, does it move well? Each line is one beat, nothing drags, and it builds to the end. |
| Originality | Does it have an angle or a line I wouldn't have thought of, or does it read as generic or AI-written? |

On any script the creator can also flag a specific problem (a fact is wrong, wrong length, off the pitch, says something I wouldn't say) and leave a comment.

For each pitch, the creator films and posts one of the usable scripts.

### Scoring

Two headline numbers are reported per model, with the five sub-scores beside them.

**Usable rate** is the share of a model's scripts rated 3 or 4. It is worked out for each creator and then averaged, so every creator counts equally. Each model's full spread of ratings, from 1 to 4, is shown in one chart beside it.

**Accuracy** is the share of a script's factual claims that are supported by the source the model cited for them. An automated checker pulls out each claim and compares it with a saved copy of the cited page. A claim with no source counts as unsupported.

**Sub-scores** are each model's average on voice, hook, substance, pacing and originality, worked out per creator and then averaged. They show where a model is strong or weak; they are not combined into one score.

Each number comes with a 95% confidence interval: the range the true value would very likely fall in if the benchmark were rerun with a different set of creators. It is calculated by resampling creators, because scripts judged by the same creator are not independent. With 250 tasks the interval is roughly plus or minus 8 points, so two models whose intervals overlap are not ranked against each other.

The number of usable scripts that were actually filmed and posted is reported alongside.

## Creators

A creator qualifies if they:

- Are an individual or small team making their own original videos.
- Make scripted, spoken, educational videos in one of the five niches, in English, 20 to 180 seconds long.
- Have at least 10 structured explainers, lists or advice videos among their recent posts.
- Are not a company, a clip aggregator, a reaction channel or a source of mass-produced AI content.

Creators are paid, agree in writing to the use of their transcripts, and are not named in results.

## Data

The tasks, scripts and creator decisions are kept private so models can't be trained on them. The prompt and tools are public, and three example tasks are in `examples/`.

## Limitations

- **Small panel.** 25 creators is enough to separate models that differ by about 10 points, not by 2 or 3.
- **Words only.** Delivery, visuals and editing are not tested, and some creators teach partly through what is on screen.
- **Willing creators.** People who agree to take part may be more open to AI scripts than creators in general.
- **Sub-scores are one person's view.** They come from the same creator who gives the overall rating, so they tend to rise and fall with it. They explain a rating more than they add independent evidence.
- **Automated accuracy.** The checker can miss an unsupported claim or wrongly flag a supported one.
- **The web changes.** Models research live, so a rerun months later will not find the same pages.
