# MMOHighlights

A general-purpose MMO raid analyzer for **Final Fantasy XIV** and **World of Warcraft**.

MMOHighlights watches raid footage — live streams or recorded VODs — and turns hours of pulls into structured, searchable moments: progress highlights, deaths, burst windows, phase transitions, and more.

## Features

### 1. Race to World First (RWF) Highlighter

Follows Race to World First events as they happen and surfaces the pulls that matter.

- Tracks multiple RWF guild/team live streams (e.g. Twitch) simultaneously
- Detects pulls and measures progress (boss HP %, phase reached, pull duration)
- Automatically clips **progress pulls** — new best attempts, new phases seen, kills
- Produces real-time highlight feeds so viewers can catch up without watching every stream

### 2. Raid VOD / Live Analyzer

Analyze your own raid footage, whether from a recorded VOD or a live stream.

- **Pull segmentation** — splits a session into individual pulls automatically
- **Deaths** — timestamps each death in every pull, with the surrounding context
- **Burst windows** — marks raid buff / cooldown windows and how they line up with the fight
- **Phase tracking** — detects phase transitions (e.g. "Phase 2 reached at 4:12")
- **Pull timeline** — a scrubbable timeline per pull with all detected events for review

## Supported Games

| Game | Status |
| --- | --- |
| Final Fantasy XIV | Planned |
| World of Warcraft | Planned |

## Roadmap

- [ ] Twitch live / VOD downloader page ([#1](https://github.com/flyxiv/MMOHighlights/issues/1))
- [ ] Pull detection from video
- [ ] Death / phase / burst window detection
- [ ] RWF multi-stream tracking and real-time highlight feed
- [ ] VOD analyzer UI with per-pull timeline

## Getting Started

The project is in early development. Setup instructions will be added once the first components land.

## Contributing

Issues and pull requests are welcome. See the [issue tracker](https://github.com/flyxiv/MMOHighlights/issues) for planned work.
