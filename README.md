# WADM

A radio station made of podcasts, programmed for one listener in Dayton, Ohio.

Twice a day WADM picks a block of episodes from the shows in `shows.yaml`,
runs each one past the bouncer, and adds them to a private podcast feed.
You follow that one feed in Apple Podcasts and press play.

## How it programs

- **Two blocks a day.** Five episodes around 5 AM, five around 4 PM (Dayton time).
- **Tiers.** Love shows play about three times as often as Fine. Fine is capped
  at two plays a week, Noise at one, so a show that uploads every day can't
  take over.
- **Whole catalogs.** A new episode airs first if it's under ten days old.
  Otherwise the station digs into the show's back catalog, so quiet shows
  still get played. An archive episode won't repeat for a year.
- **Wildcards.** About every fifth daytime play is a show on trial. A new
  wildcard joins on the first run of each month, from `candidates.yaml`.
- **After dark.** Every evening block ends with CBS Radio Mystery Theater,
  then a late-night show (Coast to Coast AM, Selected Shorts and friends).
  The two Mystery Theater feeds share stories, so the station checks titles
  across both and never airs the same story twice.
- **The bouncer.** Every episode is checked against the rule in
  `station.yaml` before it airs. With an Anthropic API key, Claude reads the
  title and show notes. Without one, keyword lists decide.
- **Trailers and teasers** under eight minutes are skipped.

The audio is never copied. Each feed item points at the original
podcast's own audio file.

## Voting

Every episode's show notes end with **More like this** and **Less like this**.
Tapping one opens a GitHub note that's already filled in; tap Submit.
The next run counts it and closes the note.

- Each net vote moves a show's weight 25% (between 0.25x and 2x).
- A wildcard with two More votes joins the regular rotation as Fine.
- A wildcard with three Less votes is retired.
- To pull any show for good, open a note titled `ditch: Show Name`.

Only notes you open count.

## Setup (one time, about ten minutes)

1. Make a free GitHub account if you don't have one.
2. Create a new **public** repository named `wadm` and upload everything in
   this folder, keeping the folder structure (including `.github`).
3. **Settings → Pages:** Source "Deploy from a branch", branch `main`,
   folder `/docs`. Save.
4. **Settings → Actions → General → Workflow permissions:** "Read and write
   permissions". Save.
5. Optional, for the Claude bouncer: **Settings → Secrets and variables →
   Actions → New repository secret**, name `ANTHROPIC_API_KEY`.
6. **Actions → WADM on the air → Run workflow.** The first run looks up
   every show's feed and builds the first block.
7. Open `https://YOUR-USERNAME.github.io/wadm/` on your phone. It has the
   feed address with a Copy button.
8. In Apple Podcasts: **Library → ··· → Follow a Show by URL**, paste.
   Open WADM, tap ···, **Settings**, and set the episode order to oldest
   first (iOS calls it "Oldest to Newest" or "Play in Sequential Order",
   depending on version) so each block plays in order. Leave Continuous
   Playback on. The feed only keeps four days, so you never fall far behind.

After that it runs itself every morning and evening.

## Changing things

| To... | Edit |
|---|---|
| Move a show between tiers, add or drop one | `shows.yaml` |
| Change block size, caps, weights, timing | `station.yaml` |
| Change the bouncer's rule or word lists | `station.yaml`, `bouncer:` |
| Change which wildcards arrive each month | `candidates.yaml` |

Vote results live in `state/overrides.json`. Delete a show's entry there to
reset it.

## Files

- `wadm/` the station code (Python)
- `state/` what has aired, bouncer verdicts, feed addresses, votes
- `docs/` the published feed, the web page and the cover art
- `tests/test_week.py` simulates two months against fake feeds and checks
  every rule (`python tests/test_week.py`)
- `.github/workflows/station.yml` the twice-daily schedule
