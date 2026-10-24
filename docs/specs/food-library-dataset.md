# Food library dataset research

Status: research note, 2026-10-24. Nutrition is still outside public-launch
scope (`plans/MYOS_LAUNCH_PRICING.md`); this note picks the source data so a
food-logging epic can start without re-doing the search.

## What we need

A shared reference set of foods, the nutrition counterpart of the Exercise
library: same for every account, no personal data, stable ids, seeded from a
file by upsert, with MYOS curation (display names, Arabic names, aliases)
stored beside the source rows (ADR 053, ADR 070).

Requirements, in priority order:

1. **A licence we can name.** The ExerciseDB media still has no confirmed
   licence (`docs/design-review/53/MEDIA-PROVENANCE.md`). A food source must
   not repeat that: the licence and attribution text are recorded before any
   row ships.
2. **Per-100 g energy, protein, carbohydrate and fat** for every row, plus
   common portions (cup, piece, slice) so a Player can log without a scale.
3. **Coverage of what our Players eat.** The launch audience is Arabic
   speaking, mostly Egyptian. Ful medames, koshari, taameya, baladi bread,
   molokhia, feteer and common Egyptian packaged brands must be findable, in
   Arabic and English.
4. **A bulk file we own a copy of**, not only a live API, so search, embeddings
   and curation work the way they do for exercises.

## Candidates

| Source | Licence | Strength | Gap |
|---|---|---|---|
| **USDA FoodData Central**: Foundation Foods + SR Legacy + FNDDS | CC0 1.0, public domain; credit requested, not required | Lab-grade generic foods (~8k SR Legacy, ~7k FNDDS mixed dishes), full macro and micronutrient panel, portion weights, CSV/JSON bulk download, stable `fdc_id` | American food names and dishes; no Arabic; few Middle Eastern dishes; SR Legacy frozen since 2018 (Foundation Foods is maintained) |
| **Open Food Facts** | ODbL (database), DbCL (contents), CC BY-SA (images) | Millions of packaged products with barcodes, nightly dumps, multilingual names including Arabic | Crowd-sourced quality; Egyptian coverage thin compared with Europe; ODbL share-alike applies to a derived database we publish |
| **Egypt NNI food composition tables** (National Nutrition Institute, 1996 edition catalogued by FAO INFOODS) | Unknown; print publication | The only source built around Egyptian foods | No machine-readable download found; licence must be asked of NNI |
| **FAO INFOODS Middle East / MEFOODS tables**, e.g. Bahrain 2025 (82 traditional dishes) | Per country, mostly unstated | Regional dishes | Mostly 1980s–1999, PDF only, no open licence found |
| **UK CoFID** (McCance & Widdowson 2021) | GOV.UK download; Quadram derived versions are CC BY-NC-SA (non-commercial) | High quality generic foods | Commercial-use terms unclear; no Arabic; not better than USDA for us |
| **FatSecret Platform API** (commercial) | Proprietary API terms | Arabic supported, localized country datasets, branded foods; free tier allows commercial use | A live API, not a file we own; caching and Egypt/Saudi coverage on the free tier unconfirmed; vendor lock-in |

## Recommendation

Build the Food library in three layers, mirroring the Exercise library:

1. **Base: USDA FoodData Central (SR Legacy + Foundation Foods).** It is the
   only large source with an unambiguous commercial licence (CC0) and a
   complete macro panel with portion weights. Import a filtered subset of
   generic foods (drop baby food, obscure game meats, brand duplicates), keep
   `fdc_id` as the stable source id, and record "USDA FoodData Central"
   provenance the way exercise rows record "ExerciseDB".
2. **MYOS-authored Egyptian and Arabic foods**, in their own id namespace
   (as `mayos:` exercises are). Start with roughly 100–200 staples: each dish
   defined as a recipe of USDA ingredients with gram weights, so its macros
   are computed from CC0 data rather than copied from a table we have no
   licence for. Owner-reviewed, with Arabic display names and aliases
   (فول، كشري، طعمية، عيش بلدي…).
3. **Food curation file** (`data/food_curation.csv`), keyed by food id:
   Arabic and English display names, aliases, hidden rows, and Egyptian
   portion names (رغيف، طبق، كوباية). Same rules as the Exercise curation
   file.

Defer packaged/branded foods and barcode scanning. When they are wanted,
**Open Food Facts** is the open option: query it live or keep its rows in a
separate table so ODbL share-alike stays limited to that table, and show its
attribution. Consider FatSecret only if Open Food Facts' Egyptian brand
coverage proves too thin, and only after reading its caching terms.

Ask NNI Egypt in writing for a licence to its food composition table. If
granted, it can replace the computed values for authored Egyptian dishes.

## Open questions for the owner

- Is nutrition a Player-only log (calories and macros against a target), or
  does the Coach prescribe a nutrition plan from day one? That decides whether
  the Food library needs meal templates in its first version.
- Do we accept computed (recipe-based) macros for Egyptian dishes, shown as
  estimates, until a licensed Egyptian table exists?

## Sources

- [FoodData Central downloads](https://fdc.nal.usda.gov/download-datasets) and [data.gov catalogue entry](https://catalog.data.gov/dataset/fooddata-central)
- [Open Food Facts licence](https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/tutorials/license-be-on-the-legal-side/) and [ODbL wiki](https://wiki.openfoodfacts.org/ODBL_License)
- [FAO INFOODS: Egypt](https://www.fao.org/infoods/infoods/tables-and-databases/egypt/en) and [Middle East tables](https://www.fao.org/infoods/infoods/tables-and-databases/middle-east/en/)
- [Bahrain food composition book 2025](https://youth.moh.gov.bh/Content/Upload/File/638913870833462746-FCT-book_2025_.pdf)
- [WHO EMRO on regional food composition gaps](https://www.emro.who.int/emhj-volume-23-2017/volume-23-issue-1/standardizing-food-composition-tables-reflecting-sugar-trans-fat-saturated-fat-and-salt-contents.html)
- [CoFID 2021 (GOV.UK)](https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/971021/McCance_and_Widdowsons_Composition_of_Foods_integrated_dataset_2021.pdf) and [Quadram CoFID terms](https://fnnbri.quadram.ac.uk/?p=34)
- [FatSecret Platform API](https://platform.fatsecret.com/)
