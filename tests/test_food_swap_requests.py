"""Assignment request queue and immutable Nutrition versions via real HTTP/SQLite."""

import json
import sqlite3

import pytest

from service import coach as coach_service
from service import food_swap_requests as request_service
from tests.test_nutrition_api import api  # noqa: F401
from tests.test_meals_api import meals_api, _ledger_id  # noqa: F401
from tests.test_coach_nutrition_drafts import coach_draft_api, _start, _publish  # noqa: F401


@pytest.fixture
def swap_queue(coach_draft_api):
    client, db, coach, player, draft_path = coach_draft_api
    record = _start(coach_draft_api)
    response = _publish(coach_draft_api, record)
    assert response.status_code == 200, response.text
    plan = client.get('/nutrition/meals', headers=player).json()
    assignment_id = draft_path.split('/')[3]
    target = {'plan_version_id': plan['plan_version_id'], 'day_type': plan['day_type'],
              'slot': plan['meals'][0]['slot'], 'food_index': 0,
              'food_id': plan['meals'][0]['foods'][0]['id']}
    return client, db, coach, player, assignment_id, target, plan


def _create(context, reason=''):
    client, _db, _coach, player, _assignment_id, target, _plan = context
    response = client.post('/nutrition/food-swap-requests', headers=player,
                           json={**target, 'reason': reason})
    assert response.status_code == 201, response.text
    return response.json()


def _decision_path(context, record, decision):
    return f'/coach/assignments/{context[4]}/food-swap-requests/{record["request_id"]}/{decision}'


def test_request_joins_assignment_and_roster_queue_without_changing_plan(swap_queue, recording_analytics):
    client, db, coach, player, assignment_id, target, plan = swap_queue
    record = _create(swap_queue)  # The reason is optional.
    assert plan['can_request_swap'] is True and plan['can_swap'] is False
    assert record['status'] == 'pending' and record['reason'] == ''
    assert _create(swap_queue)['request_id'] == record['request_id']  # Retry does not duplicate.
    assert client.get('/nutrition/meals', headers=player).json() == plan
    queue = client.get(f'/coach/assignments/{assignment_id}/program-requests', headers=coach).json()['requests']
    assert queue[0]['food_swap']['plan_version_id'] == target['plan_version_id']
    assert client.get('/coach/program-requests', headers=coach).json()['requests'][0]['kind'] == 'food_swap'
    roster = client.get('/coach/assignments', headers=coach).json()['assignments']
    assert roster[0]['pending_requests'] == 1
    assert client.get('/nutrition/food-swap-requests', headers=player).json()['requests'][0]['request_id'] == record['request_id']
    events = [event for event in recording_analytics.events if event['event'] == 'nutrition_food_swap_request_created']
    assert len(events) == 1 and events[0]['properties']['request_status'] == 'pending'
    assert 'food_id' not in events[0]['properties'] and 'reason' not in events[0]['properties']
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.get_active_nutrition_plan()['id'] == plan['plan_version_id']


@pytest.mark.parametrize('decision', ['apply', 'decline'])
def test_coach_decisions_reply_and_apply_only_once(swap_queue, recording_analytics, decision):
    client, db, coach, player, _assignment_id, target, plan = swap_queue
    record = _create(swap_queue, 'I would like another protein.')
    body = {'response': 'Use this instead.' if decision == 'apply' else 'Keep this food for now.'}
    if decision == 'apply':
        body.update(food_id='alternative', grams=plan['meals'][0]['foods'][0]['grams'])
    response = client.post(_decision_path(swap_queue, record, decision), headers=coach, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == ('applied' if decision == 'apply' else 'declined')
    assert client.post(_decision_path(swap_queue, record, decision), headers=coach, json=body).status_code == 409
    history = client.get('/nutrition/food-swap-requests', headers=player).json()['requests']
    assert history[0]['response'] == body['response'] and history[0]['status'] == response.json()['status']
    assert client.get('/coach/assignments', headers=coach).json()['assignments'][0]['pending_requests'] == 0
    with db.open_ledger(_ledger_id(db)) as ledger:
        active = ledger.get_active_nutrition_plan()
        assert active['id'] == plan['plan_version_id'] + (decision == 'apply')
        assert active['author'] == 'Coach' and active['authority_assignment_id'] == record['assignment_id']
        versions = ledger.conn.execute('SELECT meals_json FROM nutrition_plan_versions WHERE id=?',
                                       (plan['plan_version_id'],)).fetchone()
        assert json.loads(versions[0])['variants'][target['day_type']]['meals'][0]['foods'][0]['id'] == target['food_id']
        if decision == 'apply':
            payload = json.loads(active['meals_json'])
            assert payload['variants'][target['day_type']]['meals'][0]['foods'][0]['id'] == 'alternative'
    events = [event for event in recording_analytics.events if event['event'] == 'nutrition_food_swap_request_decided']
    assert len(events) == 1 and events[0]['properties']['request_status'] == response.json()['status']


@pytest.mark.parametrize('change', ['version', 'allergy', 'floor'])
def test_invalid_or_stale_application_leaves_request_pending(swap_queue, change):
    client, db, coach, player, _assignment_id, _target, plan = swap_queue
    record = _create(swap_queue)
    if change == 'version':
        # A fresh Coach publication makes the pending request stale.
        draft_path = f'/coach/assignments/{swap_queue[4]}/nutrition/draft'
        fresh = client.post(draft_path, headers=coach, json={'source': 'current'}).json()
        published = client.post(f'{draft_path}/publish', headers=coach,
                                json={'revision': fresh['revision'], 'confirm_takeover': True})
        assert published.status_code == 200, published.text
    elif change == 'allergy':
        with db.catalog_locked() as connection:
            connection.execute("UPDATE foods SET allergens_reviewed=1, allergens_json='[\"milk\"]' WHERE id='alternative'")
            connection.commit()
        with db.open_ledger(_ledger_id(db)) as ledger:
            setup = ledger.get_meal_setup()
            setup['restrictions']['allergies'] = ['milk']
            ledger.save_meal_setup(setup)
            ledger.conn.commit()
    body = {'response': 'Try this.', 'food_id': 'alternative',
            'grams': 1 if change == 'floor' else plan['meals'][0]['foods'][0]['grams']}
    response = client.post(_decision_path(swap_queue, record, 'apply'), headers=coach, json=body)
    assert response.status_code == (409 if change == 'version' else 400), response.text
    assert client.get('/nutrition/food-swap-requests', headers=player).json()['requests'][0]['status'] == 'pending'


def test_authority_is_nutrition_specific_and_ending_closes_pending_requests(swap_queue):
    client, _db, coach, player, _assignment_id, target, _plan = swap_queue
    # A Player cannot directly swap a Coach plan, or use Coach resolution endpoints.
    assert client.post('/nutrition/meals/swap', headers=player, json={
        'plan_version_id': target['plan_version_id'], 'day_type': target['day_type'],
        'slot': target['slot'], 'role': 'protein', 'food_id': 'alternative'}).status_code == 403
    record = _create(swap_queue)
    path = _decision_path(swap_queue, record, 'decline')
    assert client.post(path, headers=player, json={'response': 'No'}).status_code == 403
    ended = client.post('/assignments/me/end', headers=player)
    assert ended.status_code == 200, ended.text
    history = client.get('/nutrition/food-swap-requests', headers=player).json()['requests']
    assert history[0]['status'] == 'closed'
    assert client.post(path, headers=coach, json={'response': 'No'}).status_code == 404
    assert client.post('/nutrition/food-swap-requests', headers=player, json=target).status_code == 403
    assert client.get('/coach/program-requests', headers=coach).json()['requests'] == []


def test_foreign_coach_cannot_list_or_decide_or_read_player_requests(swap_queue):
    client, db, _coach, player, assignment_id, _target, _plan = swap_queue
    record = _create(swap_queue)
    registered = client.post('/auth/register', json={
        'trainee_id': 'foreign-swap-coach', 'password': 'correct-horse-1'}).json()
    stranger = {'Authorization': f'Bearer {registered["access_token"]}'}
    token = coach_service.issue_coach_invite(db, 'foreign-swap-coach', actor='cli')['token']
    assert client.post('/coach/invite/redeem', headers=stranger, json={'token': token}).status_code == 200
    refused = client.get(f'/coach/assignments/{assignment_id}/program-requests', headers=stranger)
    unknown = client.get('/coach/assignments/unknown/program-requests', headers=stranger)
    assert refused.status_code == unknown.status_code == 403
    assert refused.json() == unknown.json()
    assert client.post(_decision_path(swap_queue, record, 'decline'), headers=stranger,
                       json={'response': 'No'}).status_code == 404
    assert client.get('/nutrition/food-swap-requests', headers=stranger).json()['requests'] == []
    assert client.get('/nutrition/food-swap-requests', headers=player).json()['requests'][0]['status'] == 'pending'


def test_player_authored_plan_cannot_create_coach_food_swap_request(coach_draft_api):
    client, _db, _coach, player, _path = coach_draft_api
    plan = client.post('/nutrition/meals/enable', headers=player).json()
    response = client.post('/nutrition/food-swap-requests', headers=player, json={
        'plan_version_id': plan['plan_version_id'], 'day_type': plan['day_type'],
        'slot': plan['meals'][0]['slot'], 'food_index': 0, 'food_id': plan['meals'][0]['foods'][0]['id']})
    assert response.status_code == 403


def test_apply_without_coach_note_returns_a_replacement_reply(swap_queue):
    client, _db, coach, player, _assignment_id, _target, plan = swap_queue
    record = _create(swap_queue)
    response = client.post(_decision_path(swap_queue, record, 'apply'), headers=coach, json={
        'food_id': 'alternative', 'grams': plan['meals'][0]['foods'][0]['grams']})
    assert response.status_code == 200, response.text
    reply = client.get('/nutrition/food-swap-requests', headers=player).json()['requests'][0]['response']
    assert 'Alternative protein' in reply


def test_plan_insert_failure_rolls_back_the_queue_claim(swap_queue):
    client, db, _coach, player, assignment_id, _target, plan = swap_queue
    record = _create(swap_queue)
    with db.open_ledger(_ledger_id(db)) as ledger:
        ledger.conn.execute("CREATE TRIGGER reject_new_nutrition_plan BEFORE INSERT ON nutrition_plan_versions "
                            "BEGIN SELECT RAISE(ABORT, 'test write failure'); END")
        ledger.conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match='test write failure'):
        request_service.decide(db, request_service.Decision(
            record['coach_account_id'], assignment_id, record['request_id'],
            {'food_id': 'alternative', 'grams': plan['meals'][0]['foods'][0]['grams'], 'response': ''}, 'applied'))
    assert client.get('/nutrition/food-swap-requests', headers=player).json()['requests'][0]['status'] == 'pending'
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.get_active_nutrition_plan()['id'] == plan['plan_version_id']


def test_program_and_food_requests_share_the_roster_pending_count(swap_queue):
    client, db, coach, _player, assignment_id, _target, _plan = swap_queue
    food_request = _create(swap_queue)
    db.create_program_request('training-request', assignment_id, food_request['coach_account_id'],
                              food_request['player_account_id'], 'split_change', 1, None, None, None,
                              4, None, 'Change days', '2026-01-01T00:00:00+00:00')
    assert client.get('/coach/assignments', headers=coach).json()['assignments'][0]['pending_requests'] == 2
    queue = client.get('/coach/program-requests', headers=coach).json()['requests']
    assert [row['request_id'] for row in queue] == ['training-request', food_request['request_id']]


def test_account_soft_deletion_removes_food_request_content(swap_queue):
    _client, db, _coach, _player, _assignment_id, _target, _plan = swap_queue
    record = _create(swap_queue, 'Private reason')
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute("UPDATE accounts SET status='deleted' WHERE account_id=?",
                                (record['player_account_id'],))
    with db.catalog_locked() as connection:
        assert connection.execute('SELECT COUNT(*) FROM food_swap_requests').fetchone()[0] == 0


@pytest.mark.parametrize('player_allowed,coach_allowed', [(False, False), (False, True), (True, False), (True, True)])
def test_request_analytics_respect_each_actors_opt_out(swap_queue, recording_analytics, player_allowed, coach_allowed):
    client, _db, coach, player, _assignment_id, _target, _plan = swap_queue
    for headers, allowed in ((player, player_allowed), (coach, coach_allowed)):
        saved = client.put('/auth/analytics-preference', headers=headers, json={'analytics_allowed': allowed})
        assert saved.status_code == 200, saved.text
    record = _create(swap_queue)
    response = client.post(_decision_path(swap_queue, record, 'decline'), headers=coach,
                           json={'response': 'Keep this food for now.'})
    assert response.status_code == 200, response.text
    events = [event for event in recording_analytics.events
              if event['event'] in ('nutrition_food_swap_request_created', 'nutrition_food_swap_request_decided')]
    assert [(event['event'], event['distinct_id']) for event in events] == [
        *([('nutrition_food_swap_request_created', record['player_account_id'])] if player_allowed else []),
        *([('nutrition_food_swap_request_decided', record['coach_account_id'])] if coach_allowed else []),
    ]
