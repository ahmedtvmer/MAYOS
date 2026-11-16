"""Exercise the browser boundary in Node without a browser or push service."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest

from service.push_messages import ROUTES

WEB = Path(__file__).parents[1] / "mobile/web"


def _node(script, **values):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed for the Web Push browser harness")
    result = subprocess.run([node, "-e", textwrap.dedent(script)],
                            env={**os.environ, **values}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_worker_deduplicates_pushes_and_routes_clicks_inside_app():
    _node(r"""
        const fs = require('node:fs');
        const vm = require('node:vm');
        const assert = require('node:assert/strict');
        const handlers = new Map();
        const seen = new Map();
        const shown = [];
        const navigated = [];
        const opened = [];
        let focuses = 0;
        let closed = 0;
        let windows = [];
        // IndexedDB is the browser persistence boundary. Preserve asynchronous
        // read-before-transaction-completion ordering in this small fake.
        const indexedDB = {open() {
          const request = {};
          queueMicrotask(() => {
            request.result = {close() {}, transaction() {
              const tx = {objectStore() {return {
                get(key) {
                  const read = {};
                  queueMicrotask(() => {
                    read.result = seen.get(key);
                    read.onsuccess();
                    queueMicrotask(() => tx.oncomplete());
                  });
                  return read;
                },
                put(value, key) {seen.set(key, value);},
              };}};
              return tx;
            }};
            request.onsuccess();
          });
          return request;
        }};
        const scope = 'https://mayos.example/app/';
        const self = {
          registration: {scope, showNotification: async (title, options) => shown.push(options)},
          addEventListener: (name, handler) => handlers.set(name, handler),
          clients: {
            matchAll: async () => windows,
            openWindow: async url => opened.push(url),
          },
        };
        vm.runInNewContext(fs.readFileSync(process.env.WORKER, 'utf8'), {self, indexedDB, URL, Date, Set});
        const run = async (name, properties) => {
          let pending;
          handlers.get(name)({...properties, waitUntil: value => pending = value});
          await pending;
        };
        const push = payload => run('push', {data: {json: () => payload}});
        const click = url => run('notificationclick', {notification: {data: {url}, close() {closed++;}}});
        (async () => {
          await push({body: 'A little encouragement', tag: 'event-1', url: '/home?push=program'});
          await push({body: 'A little encouragement', tag: 'event-1', url: '/home?push=program'});
          assert.equal(shown.length, 1);
          assert.equal(shown[0].data.url, scope + 'home?push=program');
          const routes = JSON.parse(process.env.ROUTES);
          for (const route of Object.values(routes)) {
            const target = scope + route.slice(1);
            await click(target);
            assert.equal(opened.at(-1), target);
          }
          await click('https://attacker.example/');
          assert.equal(opened.at(-1), scope + 'home');
          windows = [
            {url: 'https://other.example/', navigate: async url => {throw Error('wrong origin');}},
            {url: scope + 'home', navigate: async url => navigated.push(url), focus: async () => focuses++},
          ];
          await click(scope + 'coach/alerts?push=coach');
          assert.equal(navigated.at(-1), scope + 'coach/alerts?push=coach');
          assert.equal(focuses, 1);
          assert.equal(closed, Object.keys(routes).length + 2);
        })().catch(error => {console.error(error); process.exitCode = 1;});
    """, WORKER=str(WEB / "push_worker.js"), ROUTES=json.dumps(ROUTES))


def test_permission_is_requested_only_by_explicit_enable_and_ios_requires_install():
    _node(r"""
        const fs = require('node:fs');
        const vm = require('node:vm');
        const assert = require('node:assert/strict');
        const source = fs.readFileSync(process.env.BRIDGE, 'utf8');
        const storage = new Map();
        let requested = 0;
        let subscribed = 0;
        let removed = 0;
        let active = null;
        const subscription = {toJSON: () => ({endpoint: 'https://fcm.googleapis.com/device', keys: {auth: 'a', p256dh: 'b'}}),
          unsubscribe: async () => removed++};
        const Notification = {permission: 'default', requestPermission() {
          requested++;
          Notification.permission = 'granted';
          return Promise.resolve('granted');
        }};
        const navigator = {userAgent: 'Desktop', platform: 'Linux', serviceWorker: {getRegistration() {return this.ready;}, ready: Promise.resolve({
          pushManager: {getSubscription: async () => active, subscribe: async options => {
            assert.equal(options.userVisibleOnly, true); subscribed++; active = subscription; return subscription;
          }},
        })}};
        const window = {Notification, PushManager: {}, matchMedia: () => ({matches: false})};
        const context = {window, navigator, Notification, Intl, Uint8Array, atob, setTimeout, clearTimeout,
          crypto: {randomUUID: () => 'device-id'},
          localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)}};
        vm.runInNewContext(source, context);
        (async () => {
          assert.equal(requested, 0);
          const state = JSON.parse(window.MAYOS_PUSH_STATE());
          assert.equal(state.permission, 'default');
          assert.equal(await window.MAYOS_PUSH_REFRESH('YQ'), null);
          assert.equal(requested, 0);
          assert.equal(subscribed, 0);
          const pending = window.MAYOS_PUSH_ENABLE('YQ');
          assert.equal(requested, 1, 'permission must begin synchronously in the tap');
          const payload = JSON.parse(await pending);
          assert.equal(payload.device_id, 'device-id');
          await window.MAYOS_PUSH_REFRESH('YQ');
          assert.equal(requested, 1, 'silent refresh must not prompt');
          assert.equal(subscribed, 1);
          await window.MAYOS_PUSH_DISABLE();
          assert.equal(removed, 1);
          navigator.userAgent = 'iPhone';
          assert.equal(JSON.parse(window.MAYOS_PUSH_STATE()).needs_install, true);
          await assert.rejects(window.MAYOS_PUSH_ENABLE('YQ'), /unsupported/);
          assert.equal(requested, 1);
          navigator.standalone = true;
          assert.equal(JSON.parse(window.MAYOS_PUSH_STATE()).needs_install, false);
        })().catch(error => {console.error(error); process.exitCode = 1;});
    """, BRIDGE=str(WEB / "push_bridge.js"))
