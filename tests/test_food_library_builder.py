import csv

import pytest

from database.food_library.builder import build_food_library


def _csv(path, fields, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_builder_applies_defaults_overrides_aliases_and_recipe_yield(tmp_path):
    foods = tmp_path / 'foods.csv'
    portions = tmp_path / 'portions.csv'
    curation = tmp_path / 'curation.csv'
    recipes = tmp_path / 'recipes.csv'
    _csv(foods, ['id','source','name','category','energy_kcal','protein_g','carbohydrate_g','fat_g','fiber_g','sugars_g','saturated_fat_g','sodium_mg'], [
        dict(id='1',source='sr_legacy',name='Pork, cooked',category='Pork',energy_kcal='200',protein_g='20',carbohydrate_g='0',fat_g='10',fiber_g='',sugars_g='0',saturated_fat_g='4',sodium_mg=''),
        dict(id='2',source='branded',name='Baby Fast Food',category='Baby Foods',energy_kcal='100',protein_g='10',carbohydrate_g='10',fat_g='2',fiber_g='1',sugars_g='2',saturated_fat_g='1',sodium_mg='20'),
        dict(id='3',source='sr_legacy',name='Rice',category='Grains',energy_kcal='100',protein_g='2',carbohydrate_g='20',fat_g='1',fiber_g='2',sugars_g='1',saturated_fat_g='0.2',sodium_mg='10'),
    ])
    _csv(portions, ['food_id','seq','label','gram_weight'], [dict(food_id='3',seq='1',label='cup',gram_weight='150')])
    _csv(curation, ['id','display_name','arabic_name','aliases_en','aliases_ar','hidden','staple_roles','portion_label','portion_grams','reviewed'], [
        dict(id='1',display_name='',arabic_name='',aliases_en='',aliases_ar='',hidden='false',staple_roles='',portion_label='',portion_grams='',reviewed='false'),
        dict(id='3',display_name='Rice',arabic_name='أرز',aliases_en='rice|white rice',aliases_ar='رز|أرز أبيض',hidden='',staple_roles='carb',portion_label='bowl',portion_grams='300',reviewed='true'),
    ])
    _csv(recipes, ['id','display_name','arabic_name','ingredient_fdc_id','grams','cooked_yield_g'], [
        dict(id='koshari',display_name='Koshari',arabic_name='كشري',ingredient_fdc_id='3',grams='200',cooked_yield_g='400'),
        dict(id='koshari',display_name='Koshari',arabic_name='كشري',ingredient_fdc_id='1',grams='200',cooked_yield_g='400')])
    rows = build_food_library(foods, portions, curation, recipes)
    assert rows == build_food_library(foods, portions, curation, recipes)
    assert rows[0]['hidden'] is False
    assert rows[0]['min_grams'] is None and rows[0]['max_grams'] is None
    assert rows[0]['fiber_g'] is None and rows[0]['sodium_mg'] is None
    assert rows[2]['aliases_ar'] == ['رز', 'أرز أبيض']
    recipe = next(row for row in rows if row['id'] == 'mayos:koshari')
    assert recipe['id'] == 'mayos:koshari'
    assert recipe['energy_kcal'] == 150
    assert recipe['portion_grams'] is None


def test_builder_fails_when_source_file_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_food_library(tmp_path / 'missing.csv', tmp_path / 'portions.csv', tmp_path / 'curation.csv', tmp_path / 'recipes.csv')


def test_catalog_seeding_path_persists_built_food_library(tmp_path, monkeypatch):
    from database.database_manager import DatabaseManager
    from database.exercise_library import embeddings
    from database.schema.definitions import EMBEDDING_DIM

    foods = tmp_path / 'foods.csv'
    portions = tmp_path / 'portions.csv'
    curation = tmp_path / 'food-curation.csv'
    recipes = tmp_path / 'food-recipes.csv'
    _csv(foods, ['id','source','name','category','energy_kcal','protein_g','carbohydrate_g','fat_g','fiber_g','sugars_g','saturated_fat_g','sodium_mg'], [
        dict(id='123',source='sr_legacy',name='Rice',category='Grains',energy_kcal='100',protein_g='2',carbohydrate_g='20',fat_g='1',fiber_g='2',sugars_g='1',saturated_fat_g='0.2',sodium_mg='10')])
    _csv(portions, ['food_id','seq','label','gram_weight'], [])
    _csv(curation, ['id','display_name','arabic_name','aliases_en','aliases_ar','hidden','staple_roles','portion_label','portion_grams','reviewed'], [
        dict(id='123',display_name='Rice',arabic_name='أرز',aliases_en='white rice',aliases_ar='رز',hidden='',staple_roles='carb',portion_label='',portion_grams='',reviewed='true')])
    _csv(recipes, ['id','display_name','arabic_name','ingredient_fdc_id','grams','cooked_yield_g','reviewed'], [
        dict(id='koshari',display_name='Koshari',arabic_name='كشري',ingredient_fdc_id='123',grams='100',cooked_yield_g='',reviewed='true')])
    exercise_curation = tmp_path / 'exercise-curation.csv'
    _csv(exercise_curation, ['id','source_name','display_name','aliases','primary_action','secondary_actions','primary_muscle','load_type','hidden','duplicate_of'], [])
    exercise_csv = tmp_path / 'exercises.csv'
    _csv(exercise_csv, ['id','name','bodyPart','target','equipment','image_path','gif_path','instructions'], [])

    class EmbeddingStub:
        def embed_query(self, _text):
            return [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    monkeypatch.setattr(embeddings, '_load_embedding_model', lambda: EmbeddingStub())
    db = DatabaseManager(catalog_path=tmp_path / 'catalog.db', ledgers_dir=tmp_path / 'users')
    try:
        db.initialize_and_seed(exercise_csv, exercise_curation,
                               food_path=foods, portion_path=portions,
                               food_curation_path=curation, recipe_path=recipes)
        row = db.catalog_conn.execute('SELECT id, name, arabic_name, hidden FROM foods').fetchone()
        assert tuple(row) == ('123', 'Rice', 'أرز', 0)
        assert db.catalog_conn.execute("SELECT reviewed FROM foods WHERE id='mayos:koshari'").fetchone()[0] == 1
        _csv(recipes, ['id','display_name','arabic_name','ingredient_fdc_id','grams','cooked_yield_g','reviewed'], [])
        db.initialize_and_seed(exercise_csv, exercise_curation, food_path=foods, portion_path=portions,
                               food_curation_path=curation, recipe_path=recipes)
        assert db.catalog_conn.execute("SELECT 1 FROM foods WHERE id='mayos:koshari'").fetchone() is None
    finally:
        db.catalog_conn.close()


def test_default_hidden_rules_and_curated_overrides(tmp_path):
    foods = tmp_path / 'foods.csv'
    portions = tmp_path / 'portions.csv'
    curation = tmp_path / 'curation.csv'
    recipes = tmp_path / 'recipes.csv'
    fields = ['id','source','name','category','energy_kcal','protein_g','carbohydrate_g','fat_g','fiber_g','sugars_g','saturated_fat_g','sodium_mg']
    names = [
        ('1','Plain baby cereal','Baby Foods'), ('2','QUAKER oatmeal','Grains'),
        ('3','KFC chicken','Restaurant Foods'), ('4','Roasted chicken','Fast Foods'),
        ('5','Pork chop','Pork Products'), ('6','Beer','Liquor and cocktails'),
        ('7','Turkey, NS as to fat','Poultry Products'),
        ('8','Turkey, fat added','Poultry Products'),
        ('9','Turkey, no added fat','Poultry Products'),
        ('10','QUAKER Energy drink','Beverages'), ('15','Restaurant meal','Restaurant Foods'),
        ('16','Energy drink (Full Throttle)','Beverages'), ('17','Energy drink (Full Throttle)','Beverages'),
        ('11',"WENDY'S burger",'Restaurant Foods'), ('12','MALT-O-MEAL cereal','Breakfast Cereals'),
        ('13','CHOBANI yogurt','Dairy and Egg Products'),
        ('14','Unbranded USDA DHA ARA UHT food','Other'),
    ]
    _csv(foods, fields, [dict(id=i,source='fndds',name=n,category=c,energy_kcal='100',protein_g='1',carbohydrate_g='2',fat_g='3',fiber_g='4',sugars_g='5',saturated_fat_g='6',sodium_mg='7') for i,n,c in names])
    _csv(portions, ['food_id','seq','label','gram_weight'], [])
    columns = ['id','display_name','arabic_name','aliases_en','aliases_ar','hidden','staple_roles','portion_label','portion_grams','reviewed']
    _csv(curation, columns, [
        dict(id='2',display_name='',arabic_name='',aliases_en='',aliases_ar='',hidden='false',staple_roles='',portion_label='',portion_grams='',reviewed='false'),
        dict(id='10',display_name='',arabic_name='',aliases_en='',aliases_ar='',hidden='true',staple_roles='',portion_label='',portion_grams='',reviewed='false'),
        dict(id='5',display_name='',arabic_name='',aliases_en='',aliases_ar='',hidden='false',staple_roles='',portion_label='',portion_grams='',reviewed='false'),
        dict(id='15',display_name='',arabic_name='',aliases_en='',aliases_ar='',hidden='',staple_roles='',portion_label='',portion_grams='',reviewed='false'),
        dict(id='16',display_name='',arabic_name='',aliases_en='',aliases_ar='',hidden='true',staple_roles='',portion_label='',portion_grams='',reviewed='false'),
    ])
    _csv(recipes, ['id','display_name','arabic_name','ingredient_fdc_id','grams','cooked_yield_g'], [])
    rows = {row['id']: row for row in build_food_library(foods, portions, curation, recipes)}
    assert all(rows[key]['hidden'] for key in ('1','3','4','6','7','11','12','13'))
    assert not rows['2']['hidden'] and not rows['5']['hidden']
    assert not rows['8']['hidden'] and not rows['9']['hidden']
    assert rows['10']['hidden']
    assert rows['15']['hidden']
    assert rows['16']['hidden']
    assert not rows['17']['hidden']
    assert not rows['14']['hidden']


def test_real_usda_rows_follow_halal_alcohol_fast_food_and_baby_rules(tmp_path):
    from database.food_library.builder import FOOD_PATH, PORTION_PATH

    if not FOOD_PATH.is_file() or not PORTION_PATH.is_file():
        pytest.skip("Real USDA row coverage requires optional data/food_library.csv and data/food_portions.csv")
    curation = tmp_path / 'curation.csv'
    recipes = tmp_path / 'recipes.csv'
    _csv(curation, ['id','display_name','arabic_name','aliases_en','aliases_ar','hidden','staple_roles','portion_label','portion_grams','reviewed'], [])
    _csv(recipes, ['id','display_name','arabic_name','ingredient_fdc_id','grams','cooked_yield_g','reviewed'], [])
    rows = {row['source_name']: row for row in build_food_library(FOOD_PATH, PORTION_PATH, curation, recipes)}
    for name in (
        'Bacon biscuit sandwich', 'Margarita',
        'Antipasto with ham, fish, cheese, vegetables',
        'Cheeseburger slider, from fast food', 'Infant formula, amino acids',
        'Alcoholic beverage, distilled, all (gin, rum, vodka, whiskey) 80 proof',
    ):
        assert rows[name]['hidden'] is True, name
    for name in (
        'Bacon strip, meatless', 'Soft drink, root beer', 'Wine, nonalcoholic',
        'Double hamburger, on wheat bun, 2 large patties', 'Energy drink (Monster)',
    ):
        assert rows[name]['hidden'] is False, name
    assert rows['Turkey bacon, cooked']['hidden'] is False
    assert rows['Beef, bacon, cooked']['hidden'] is False
    assert rows['Beer']['hidden'] is True
    assert rows['Wine, red']['hidden'] is True
    assert rows['Pork, belly']['hidden'] is True
    assert rows['Baby Toddler apples, Stage 1']['hidden'] is True


def test_recipe_reviewed_flag_defaults_false_and_accepts_true(tmp_path):
    foods = tmp_path / 'foods.csv'
    portions = tmp_path / 'portions.csv'
    curation = tmp_path / 'curation.csv'
    recipes = tmp_path / 'recipes.csv'
    fields = ['id','source','name','category','energy_kcal','protein_g','carbohydrate_g','fat_g','fiber_g','sugars_g','saturated_fat_g','sodium_mg']
    _csv(foods, fields, [dict(id='1',source='sr_legacy',name='Rice',category='Grains',energy_kcal='100',protein_g='2',carbohydrate_g='20',fat_g='1',fiber_g='2',sugars_g='1',saturated_fat_g='0.2',sodium_mg='10')])
    _csv(portions, ['food_id','seq','label','gram_weight'], [])
    _csv(curation, ['id','display_name','arabic_name','aliases_en','aliases_ar','hidden','staple_roles','portion_label','portion_grams','reviewed'], [])
    recipe_fields = ['id','display_name','arabic_name','ingredient_fdc_id','grams','cooked_yield_g','reviewed']
    _csv(recipes, recipe_fields, [
        dict(id='estimate',display_name='Estimate',arabic_name='تقدير',ingredient_fdc_id='1',grams='100',cooked_yield_g='',reviewed=''),
        dict(id='approved',display_name='Approved',arabic_name='معتمد',ingredient_fdc_id='1',grams='100',cooked_yield_g='',reviewed='true'),
    ])
    rows = {row['id']: row for row in build_food_library(foods, portions, curation, recipes)}
    assert rows['mayos:estimate']['reviewed'] is False
    assert rows['mayos:approved']['reviewed'] is True


@pytest.mark.parametrize(('grams', 'yield_grams', 'message'), [
    ('0', '', 'ingredient grams'), ('-2', '', 'ingredient grams'),
    ('100', '0', 'cooked yield'), ('100', '-1', 'cooked yield'),
])
def test_recipe_rejects_non_positive_weights(tmp_path, grams, yield_grams, message):
    foods = tmp_path / 'foods.csv'
    portions = tmp_path / 'portions.csv'
    curation = tmp_path / 'curation.csv'
    recipes = tmp_path / 'recipes.csv'
    _csv(foods, ['id','source','name','category','energy_kcal','protein_g','carbohydrate_g','fat_g','fiber_g','sugars_g','saturated_fat_g','sodium_mg'], [
        dict(id='1',source='sr_legacy',name='Rice',category='Grains',energy_kcal='100',protein_g='2',carbohydrate_g='20',fat_g='1',fiber_g='2',sugars_g='1',saturated_fat_g='0.2',sodium_mg='10')])
    _csv(portions, ['food_id','seq','label','gram_weight'], [])
    _csv(curation, ['id','display_name','arabic_name','aliases_en','aliases_ar','hidden','staple_roles','portion_label','portion_grams','reviewed'], [])
    _csv(recipes, ['id','display_name','arabic_name','ingredient_fdc_id','grams','cooked_yield_g','reviewed'], [
        dict(id='bad',display_name='Bad',arabic_name='سيئ',ingredient_fdc_id='1',grams=grams,cooked_yield_g=yield_grams,reviewed='')])
    with pytest.raises(ValueError, match=message):
        build_food_library(foods, portions, curation, recipes)
