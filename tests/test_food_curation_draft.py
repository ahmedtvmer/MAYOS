import csv

import pytest

from database.food_library.builder import CURATION_PATH, FOOD_PATH, PORTION_PATH, RECIPE_PATH, build_food_library


def test_owner_food_draft_has_required_arabic_aliases_and_unreviewed_recipes():
    if not FOOD_PATH.is_file() or not PORTION_PATH.is_file():
        pytest.skip("Owner draft USDA coverage requires optional data/food_library.csv and data/food_portions.csv")
    rows = build_food_library()
    foods = {row['id']: row for row in rows}
    with CURATION_PATH.open(encoding='utf-8') as stream:
        curated = list(csv.DictReader(stream))
    with RECIPE_PATH.open(encoding='utf-8') as stream:
        recipes = list(csv.DictReader(stream))
    assert 200 <= len([row for row in curated if row['arabic_name']]) <= 300
    assert all(row['reviewed'].lower() == 'false' for row in curated)
    curated_by_id = {row['id']: row for row in curated}
    assert curated_by_id['2709196']['arabic_name'] == 'تفاح مجفف'
    assert curated_by_id['168877']['arabic_name'] == 'أرز أبيض نيء'
    assert not any(name in row['arabic_name'] for row in curated for name in ('بلاكك', 'اببليس', 'سولفوريد'))
    assert curated_by_id['2707730']['aliases_en'] == 'baladi bread|whole-wheat pita'
    assert curated_by_id['173417']['aliases_en'] == 'areesh'
    assert curated_by_id['173417']['aliases_ar'] == 'جبنة قريش|جبن قريش'
    assert all(row['hidden'] is False for row in rows if row['id'] in curated_by_id)
    assert not any('sulfured' in row['source_name'].lower() for row in rows if row['id'] in curated_by_id)
    aliases = {alias for row in curated for alias in row['aliases_ar'].split('|') if alias}
    assert {
        'عيش بلدي', 'فول', 'فول مدمس', 'طعمية', 'جبنة قريش', 'جبنة رومي',
        'بيض', 'رز', 'عدس', 'مكرونة', 'فراخ',
    } <= aliases
    assert {row['id'].removeprefix('mayos:') for row in rows if row['id'].startswith('mayos:')} >= {
        'koshari', 'ful_medames', 'taameya', 'chicken_shawerma', 'chicken_pane',
        'molokhia', 'mahshi', 'fattah', 'basbousa', 'feteer_meshaltet',
        'mesakaa', 'tahini_salad', 'baba_ghanoush', 'lentil_soup', 'rice_vermicelli',
    }
    assert all(row['reviewed'].lower() == 'false' for row in recipes)
    assert all(foods[row['ingredient_fdc_id']]['hidden'] is False for row in recipes)
    ingredients = {
        recipe_id: {row['ingredient_fdc_id'] for row in recipes if row['id'] == recipe_id}
        for recipe_id in {row['id'] for row in recipes}
    }
    assert {'168877', '172420', '169736', '2644282', '2710186'} <= ingredients['koshari']
    assert '174158' in ingredients['lentil_soup']
    assert all(float(row['cooked_yield_g']) > 0 for row in recipes if row['cooked_yield_g'])
    roles = {role for row in curated for role in row['staple_roles'].split('|') if role}
    assert {'breakfast_protein', 'main_protein', 'carb', 'vegetable_fat', 'snack'} <= roles
    assert 'breakfast_protein' in foods['173798']['staple_roles']
    assert 'main_protein' in foods['2707152']['staple_roles']
