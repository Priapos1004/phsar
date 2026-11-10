---
date: 2026-11-07
version: v0.16.5
branch: v0.16.5-galaxy-map
topic: Hand names for every sector and region of the first prod galaxy fit, and the conventions behind them
status: shipped
related:
  - 2026-10-30-v0.16.5-galaxy.md
---

# v0.16.5 — Galaxy names for the first prod fit

## Summary

The first prod fit (2026-11-07, 1,962 stars in 17 sectors and 53 regions) showed only
auto names, which list over-represented tags ("Shounen · Manga", "mixed") and say little
about what a group holds. Every group now carries a hand name, chosen with the user one
by one. Hand names follow their members onto each refit ([galaxy](../docs/features/galaxy.md#names)),
so this record is what the naming pass after the next refit
([when the map is rebuilt](../docs/features/galaxy.md#when-the-map-is-rebuilt)) starts from.

## Key decisions

**A name must work as a map label.** Labels wrap at the widths in `nameStyle`
(`GalaxyMap.svelte`), so names aim for 25 characters or fewer; the longest are 29 and
take two lines. Past the region zoom, region names replace sector names
([USER_FLOWS §3d](../phsar/frontend/USER_FLOWS.md#3d-galaxy)), so a region name has to
read on its own: "Modern Mecha", not "Modern".

**Content over judgement.** Score and era words appear only where the fit split a sector
on them ([regions cluster on both](../docs/features/galaxy.md#the-fit)): Modern / Classic
Battle Shounen, Modern / Retro Mecha, Seinen Classics / New Seinen Drama. The auto names'
"acclaimed" and "low-rated" otherwise went.

**Plain words over genre jargon**, and the friendlier phrasing when two are equally true.
"Space Opera" became "Starships", and the user picked "Seinen Love & Laughs" over
"Seinen Rom-Coms & Gag Comedy", "Performers & Athletes" over "Music, Idols & Sports",
"Comedy & Spirit Oddities" over "Offbeat Donghua & Shorts" and "Demon Lords Back at
School" over "Reborn Demon Lord Academy".

**A name may not over-claim its members.** "Gritty Seinen Classics" fit Vinland Saga and
Parasyte but not Mushishi, Space Brothers or Delicious in Dungeon in the same region.
"Spooky Spirit Donghua" fit its region's horror half but not Luoxiaohei or Big Fish &
Begonia. "Grounded Seinen Drama" described Seinen Classics' Monster just as well, so it
lost to "New Seinen Drama". A region made of two clusters names both halves: "Villainess
& Josei Drama".

**Sibling sectors read as sets.** The demographic sectors are Shounen Manga / Seinen
Manga / Shoujo & Josei. The two isekai sectors split on how the hero arrives, so they are
Transported to Another World / Reborn in Another World.

**No two names near-twins anywhere on the map.** The per-sector proposals collided across
sectors, and these lost: "Xianxia Cultivation Sagas" beside the sector "Xianxia
Cultivation Epics" (now Sect & Cultivation Donghua), "Fantasy Comedy & Parody" beside
"Fantasy Comedy Shorts" (now Isekai Gags & Parody), and "Superpower Thrillers", which
would have been the map's third "Thrillers" (now Psychics, Agents & Heroes). Shounen
Rom-Coms dropped "& Harems", which Ecchi Harem Rom-Coms owns, and Shounen Sports & Stage
took "Stage" over "Music", which Performers & Athletes owns. "Rom-Coms" is spelt one way,
and "Anime" is never in a name.

## The names

Groups are numbered as at this fit; after a refit, the anchor titles are what identify a
group again. ⚠ marks the grab-bag groups, where the name is the best umbrella rather than
a common thread.

| Group | Stars | Name | Anchors | Why |
|---|---|---|---|---|
| **S0** | 244 | Shounen Manga | One Piece, Jujutsu Kaisen, Haikyu!!, Death Note | 97% shounen, of every genre |
| R0 | 64 | Shounen Rom-Coms | Takagi-san, Quintessential Quintuplets, Horimiya, To LOVE-Ru | — |
| R1 | 56 | Shounen Action-Comedy | Spy x Family, Saiki K., Mashle, Sakamoto Days | light-toned, quirky premises |
| R2 | 28 | Modern Battle Shounen | Jujutsu Kaisen, Demon Slayer, Attack on Titan, Fullmetal Alchemist | the big franchises from 2003 on |
| R3 | 24 | Classic Battle Shounen | Dragon Ball, Naruto, Bleach, Yu Yu Hakusho | the '70s–early '00s pillars |
| R4 | 14 | Shounen Sports & Stage | Haikyu!!, Kuroko's Basketball, Your Lie in April, Kono Oto Tomare! | — |
| R5 | 32 | Supernatural Shounen | Noragami, Dan Da Dan, Toilet-Bound Hanako-kun, Call of the Night | spirits, yokai, vampires |
| R6 | 12 | Retro Shounen Sports & Comedy | Captain Tsubasa, Ashita no Joe, Touch, Urusei Yatsura | '70s–'80s shounen that isn't battle |
| R7 | 14 | Dark Shounen Thrillers | Death Note, The Promised Neverland, Summer Time Rendering, Kakegurui | mind games and death games |
| **S1** | 136 | Seinen Manga | Vinland Saga, Monster, Kaguya-sama, [Oshi no Ko] | the demographic is the only common thread |
| R8 | 31 | Seinen Classics | Monster, Akira, Ghost in the Shell, Mushishi | the acclaimed canon: median 8.0 against the sector's 7.5, ~2012 |
| R9 ⚠ | 31 | Seinen Fantasy & Ecchi Romps | Monster Musume, One-Punch Man, Hinamatsuri, Tales of Wedding Rings | pulpy genre seinen, with prestige strays (Witch Hat Atelier, Land of the Lustrous) |
| R10 | 40 | Seinen Love & Laughs | Kaguya-sama, My Dress-Up Darling, Grand Blue, Asobi Asobase | romcoms beside gag comedy |
| R11 | 34 | New Seinen Drama | [Oshi no Ko], Orb, Skip and Loafer, Medalist | realistic sport, stage and everyday life, median 2025 |
| **S2** | 75 | Shoujo & Josei | Fruits Basket, Nana, Yona of the Dawn, Chihayafuru | 68% shoujo, 20% josei |
| R12 | 31 | Villainess & Josei Drama | My Next Life as a Villainess, Tearmoon Empire; Chihayafuru, Nodame Cantabile | two clusters; nearly every member is `between` |
| R13 | 44 | Shoujo Manga Romance | Kimi ni Todoke, Maid Sama!, Hana Yori Dango, Snow White with the Red Hair | 100% shoujo, 1967–2026, so the auto name's "classic" was wrong |
| **S3** | 87 | Performers & Athletes | Bocchi the Rock!, Love Live!, Yuri!!! on Ice, Run with the Wind | performance and competition outside shounen |
| R14 | 36 | Sports & Hobby Clubs | SK8 the Infinity, Free!, Uma Musume, Girls und Panzer | original sports and CGDCT clubs |
| R15 | 51 | Idols & Bands | Love Live!, The iDOLM@STER, BanG Dream!, Sound! Euphonium | — |
| **S4** | 179 | Mascots & Preschool TV | Chiikawa, Sumikko Gurashi, Pleasant Goat and Big Big Wolf, Tayo | the youngest audience and goods mascots |
| R16 | 119 | Cute Mascot Shorts | Bananya, Rilakkuma and Kaoru, Pui Pui Molcar, Mofusand | also takes the one-off films nothing else does |
| R17 | 60 | Preschool Cartoon Series | Tayo, Super Wings, Larva, Boonie Bears | long-running episodic TV, much of it Korean or Chinese |
| **S5** | 71 | Giant Robots & Starships | Gundam, Evangelion, Macross, Space Battleship Yamato | — |
| R18 | 51 | Modern Mecha | Gundam 00, Gurren Lagann, Code Geass, 86 | Evangelion onward |
| R19 | 20 | Retro Mecha & Starships | Yamato, Captain Harlock, Mobile Suit Gundam (1979), Votoms | the Showa founders |
| **S6** | 59 | Long-Running Kids' TV | Doraemon, Pokémon, Pretty Cure, Sazae-san | broadcast franchises for older kids |
| R20 | 52 | Magical Girls & Family TV | Pretty Cure, Ojamajo Doremi, Chibi Maruko-chan, Heidi | its two largest groups |
| R21 | 7 | Card & Game Battles | Yu-Gi-Oh! Sevens, Cardfight!! Vanguard, Duel Masters, Shadowverse | shows built to sell a game |
| **S7** | 155 | Mystery, Suspense & Drama | Steins;Gate, Death Parade, Odd Taxi, Darker than Black | psychological, mystery and suspense, mostly originals |
| R22 | 38 | Yokai & Detective Mysteries | The Eccentric Family, The Morose Mononokean, Shoshimin, The Millionaire Detective | two strands, both novel adaptations |
| R23 | 43 | Psychological Thrillers | Perfect Blue, Madoka Magica, Higurashi, Danganronpa | dark magical girls link the thrillers and death games |
| R24 | 27 | Samurai & Crime Action | Samurai Champloo, Great Pretender, 91 Days, Lycoris Recoil | two kinds of stylish action |
| R25 | 22 | Ghibli & Shinkai Films | Spirited Away, My Neighbor Totoro, Your Name., A Place Further Than the Universe | the two studios at the top, wistful original dramas around them |
| R26 | 25 | Psychics, Agents & Heroes | Darker than Black, Charlotte, Tiger & Bunny, Link Click | ability users in dark plots |
| **S8** | 100 | Standalone Sci-Fi & Drama | Vivy, Bubble, Lost in Starlight, Metallic Rouge | one-off works with no franchise behind them |
| R27 | 69 | Sci-Fi Originals & Films | Vivy, NieR:Automata, Moonrise, Junk Head | androids, space, time travel |
| R28 ⚠ | 31 | Drama & Mystery Films | Mom, I'm Sorry; Your Letter; Fureru.; Whoever Steals This Book | the sector's non-sci-fi side, half from China, Korea or Thailand |
| **S9** | 61 | Comedy & Spirit Oddities | The Legend of Luoxiaohei, God Troubles Me, Jantama Pong | the low-profile offbeat corner, mostly non-cultivation donghua |
| R29 ⚠ | 42 | Fantasy Comedy Shorts | Cooking with Valkyries, Fate/Grand Order shorts, Mahjong Soul Pon | gag donghua beside tie-in shorts |
| R30 | 19 | Spirit & Monster Donghua | Luoxiaohei, Big Fish & Begonia, God Troubles Me, YaShe | spirits, gods, vampires; critter shorts at the edge |
| **S10** | 129 | Sword & Sorcery Adventure | Sword Art Online, Goblin Slayer, Ranking of Kings, Log Horizon | native-world fantasy, beside the isekai and cultivation sectors |
| R31 ⚠ | 28 | Dramatic & Historical Fantasy | Violet Evergarden, Made in Abyss; Solo Leveling, Tower of God | two threads: period drama and webtoon regressors |
| R32 | 67 | Adventurer Parties & Guilds | Beast Tamer, Party of None, Cautious Hero, Let This Grieving Soul Retire | guild ranks and the kicked-from-the-party trope |
| R33 | 34 | Game Worlds & Fantasy Wars | Sword Art Online, BOFURI, Alderamin on the Sky, Record of Grancrest War | VRMMOs beside war chronicles |
| **S11** | 51 | Xianxia Cultivation Epics | Soul Land, Battle Through the Heavens, A Record of Mortal's Journey to Immortality, Mo Dao Zu Shi | the acclaimed cultivation core |
| R34 | 51 | Xianxia & Wuxia Donghua | Perfect World, Swallowed Star, A Will Eternal, Qin's Moon | the sector's only region |
| **S12** | 202 | New-Wave Donghua | Martial Peak, Lord of Mysteries, Ne Zha, Release that Witch | the newer wave around S11, median 2024 |
| R35 | 29 | Donghua Romance & Comedy | Fox Spirit Matchmaker, Psychic Princess, How Dare You!?, The Richest Man in Game | donghua that aren't cultivation battles |
| R36 | 50 | Wuxia & Historical Action | The Ravages of Time, Blades of the Guardians, Word of Honor, Lantern Blade | swordplay, Three Kingdoms, court drama |
| R37 ⚠ | 28 | Donghua Myth & Sci-Fi | Ne Zha, White Snake; The First Order, The Other Side of Deep Space | two strands united by what they aren't |
| R38 | 77 | Sect & Cultivation Donghua | Martial Peak, Martial God Asura, Dragon Prince Yuan, Swallowing the Heavens | the dense 2024–26 web-novel core |
| R39 ⚠ | 18 | Urban Powers & Game Shorts | Super Cube, Crowned from the Start, Genshin Impact shorts | a third of it placed or `between` |
| **S13** | 81 | Transported to Another World | Re:ZERO, No Game No Life, Overlord, KonoSuba | the hero arrives as themselves, and isekai parody |
| R40 | 28 | Isekai Gags & Parody | Uncle from Another World, Isekai Quartet, Interspecies Reviewers | trope send-ups with a raunchy wing |
| R41 | 53 | Cheat-Skill Isekai Quests | The Rising of the Shield Hero, Arifureta, Tsukimichi, In Another World With My Smartphone | the straight isekai adventure |
| **S14** | 86 | Reborn in Another World | Mushoku Tensei, Ascendance of a Bookworm, So I'm a Spider, So What?, Reincarnated as a Sword | — |
| R42 | 65 | Reincarnated & Overpowered | The Eminence in Shadow, I Was Reincarnated as the 7th Prince, Wise Man's Grandchild | — |
| R43 | 18 | Cozy Isekai: Food & Family | Campfire Cooking in Another World, Restaurant to Another World, Farming Life in Another World | low stakes, no fighting |
| R44 | 3 | Demon Lords Back at School | The Misfit of Demon King Academy, The Greatest Demon Lord Is Reborn as a Typical Nobody, The Demon Sword Master of Excalibur Academy | an ancient demon lord enrols at a magic academy |
| **S15** | 191 | Rom-Coms & Love Stories | Toradora!, My Teen Romantic Comedy SNAFU, Bunny Girl Senpai, Wotakoi | romance not led by shoujo |
| R45 | 80 | High School Rom-Coms | Toradora!, SNAFU, Makeine, Alya Sometimes Hides Her Feelings in Russian | male-led school romcoms and Key dramas |
| R46 | 14 | Cozy Slice of Life | Laid-Back Camp, Miss Kobayashi's Dragon Maid, Barakamon, Bunny Drop | — |
| R47 ⚠ | 41 | Romance Drama & Supernatural | Josee, the Tiger and the Fish; Golden Time; The Devil is a Part-Timer!; Spice and Wolf | held together by being past high school |
| R48 | 15 | Fantasy Court Romance | The Too-Perfect Saint, Your Broken Saintess, Saved by the Ice Cold Prince's Embrace | a cast-off saint taken in by a prince, no reincarnation |
| R49 | 32 | Workplace & Adult Rom-Coms | Wotakoi, My Senpai is Annoying, Uzaki-chan Wants to Hang Out!, Life Lessons with Uramichi-Oniisan | working adults and teasing romcoms |
| R50 | 9 | Boys' Love | Junjo Romantica, Cherry Magic!, Hitorijime My Hero | every member is BL |
| **S16** | 55 | Ecchi, Harem & Urban Fantasy | High School DxD, Kill la Kill, Date A Live, A Certain Magical Index | 2010s late-night light-novel adaptations |
| R51 | 25 | Urban Fantasy Battles | Fate/stay night, A Certain Magical Index, The Irregular at Magic High School | hidden magic in modern cities, Type-Moon and Toaru at the core |
| R52 | 30 | Ecchi Harem Rom-Coms | High School DxD, Haganai, Shomin Sample, Shimoneta | — |

## Gotchas & learnings

- **`/browse/galaxy` needs a login.** Any account will do, the guest included; an
  anonymous request is a 401.
- **Check `fitted_at` before patching.** Group uuids belong to one fit; if `fitted_at` or
  the set of uuids no longer matches the snapshot the names were chosen from, a refit came
  between and every PATCH misses.
- **A name that doesn't carry is gone.** The rebuild's Jobs Log row reports only how many
  names it kept, and the map serves only the resolved name. A lost name shows up as a
  live name missing from this table, and this table is where it is recovered from.
- **Titles carry the naming, not tags.** The payload has no studio or source, and the
  majority tags are patchy (Code Geass carries only "School"). Each sector went to its own
  subagent with a brief listing every member (title, majority tags, MAL score, year,
  `trained`, `between`), each region's tag lift against its sector, and an overview of all
  sectors to keep names apart. The subagents leant on what they knew of the titles.

## Future work / debt

- **After the next refit**, rename the groups whose names didn't carry, re-read the ⚠
  groups (their names are umbrellas, so they drift first), and re-check every name that
  is relative to today: New Seinen Drama, New-Wave Donghua.
- **"Ghibli & Shinkai Films" over-claims "Films"**: about half its members are TV series.
  "Heartfelt Drama & Wonder" is the fallback if it reads wrong on the map.
- **The rebuild counts dropped names instead of listing them.** Listing them in its
  `result_summary` would make a lost name findable without this table; worth it once a
  refit drops names that matter.
- **The fit holds strays that naming could only paper over**: literary adaptations (Anne
  of Green Gables, Aoi Bungaku) in Giant Robots & Starships, a placed cluster of Korean
  toy-robot shows in Modern Mecha, and Bocchi the Rock! in Sports & Hobby Clubs rather
  than Idols & Bands.
