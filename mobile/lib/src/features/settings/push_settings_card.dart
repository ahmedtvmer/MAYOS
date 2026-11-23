import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/display_language/controller.dart';
import '../../core/push_device.dart';
import '../../providers.dart';

/// The compact variant is offered only after a completed workout on Home.
class PushSettingsCard extends ConsumerStatefulWidget {
  const PushSettingsCard({super.key, this.compact = false});
  final bool compact;

  @override
  ConsumerState<PushSettingsCard> createState() => _PushSettingsCardState();
}

class _PushSettingsCardState extends ConsumerState<PushSettingsCard> {
  Map<String, dynamic>? _status;
  Map<String, dynamic> _device = <String, dynamic>{};
  bool _busy = false;
  bool _dismissed = false;
  bool _failed = false;
  String? _accountId;

  bool get _ar => ref.read(displayLanguageProvider).startsWith('ar');
  String _copy(String en, String ar) => _ar ? ar : en;
  String get _dismissKey => 'mayos.push.dismissed.$_accountId';
  Map<String, dynamic> get _prefs =>
      Map<String, dynamic>.from(_status!['preferences'] as Map);

  @override
  void initState() {
    super.initState();
    _accountId = ref.read(authControllerProvider).session?.account.accountId;
    if (kIsWeb) _load();
  }

  bool get _ownsAccount =>
      mounted &&
      _accountId != null &&
      ref.read(authControllerProvider).session?.account.accountId == _accountId;

  /// Reads the push status, from the session cache unless [refresh] (#756).
  Future<void> _load({bool refresh = false}) async {
    try {
      _device = pushDeviceState();
      _dismissed =
          ref.read(browserKeyValueStoreProvider).getItem(_dismissKey) == '1';
      final String deviceId = _device['device_id'] as String;
      final cached = ref.read(pushStatusCacheProvider);
      final Map<String, dynamic> status =
          !refresh && cached != null && cached.deviceId == deviceId
              ? cached.status
              : await ref.read(apiClientProvider).pushStatus(deviceId);
      if (!_ownsAccount) return;
      ref.read(pushStatusCacheProvider.notifier).state =
          (deviceId: deviceId, status: status);
      setState(() {
        _status = status;
        _failed = false;
      });
    } on Object {
      if (_ownsAccount) setState(() => _failed = true);
    }
  }

  Future<void> _enable() async {
    // This call starts before any await, preserving the originating tap.
    final pending = enablePushDevice(_status!['public_key'] as String);
    setState(() {
      _busy = true;
      _failed = false;
    });
    try {
      final subscription = await pending;
      if (!_ownsAccount) return;
      if (subscription != null && subscription.containsKey('endpoint')) {
        await ref.read(apiClientProvider).savePushSubscription(subscription);
        if (!_ownsAccount) return;
        final prefs = _prefs;
        prefs['timezone'] = _device['timezone'] ?? prefs['timezone'];
        await ref.read(apiClientProvider).savePushPreferences(prefs);
      }
      await _load(refresh: true);
    } on Object {
      if (_ownsAccount) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _disable() async {
    setState(() {
      _busy = true;
      _failed = false;
    });
    try {
      await ref
          .read(apiClientProvider)
          .deletePushSubscription(_device['device_id'] as String);
      await disablePushDevice();
      await _load(refresh: true);
    } on Object {
      if (_ownsAccount) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save(String key, Object value) async {
    final prefs = _prefs;
    prefs[key] = value;
    // The schedule timezone wins server-side; browser timezone is the fallback.
    if (prefs['timezone'] == 'UTC')
      prefs['timezone'] = _device['timezone'] ?? 'UTC';
    setState(() {
      _busy = true;
      _failed = false;
    });
    try {
      await ref.read(apiClientProvider).savePushPreferences(prefs);
      await _load(refresh: true);
    } on Object {
      if (_ownsAccount) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _time(String key) async {
    final parts = (_prefs[key] as String).split(':');
    final selected = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(
        hour: int.parse(parts[0]),
        minute: int.parse(parts[1]),
      ),
    );
    if (selected != null && _ownsAccount) {
      await _save(
        key,
        '${selected.hour.toString().padLeft(2, '0')}:${selected.minute.toString().padLeft(2, '0')}',
      );
    }
  }

  void _dismiss() {
    ref.read(browserKeyValueStoreProvider).setItem(_dismissKey, '1');
    setState(() => _dismissed = true);
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    if (!kIsWeb) {
      return widget.compact
          ? const SizedBox.shrink()
          : Text(
              _copy(
                'Push notifications are available in the installed web app.',
                'تتوفر الإشعارات في تطبيق الويب المثبّت.',
              ),
            );
    }
    final status = _status;
    final subscribed = status?['subscribed'] == true;
    if (widget.compact &&
        (_dismissed ||
            status == null ||
            status['enabled'] != true ||
            subscribed ||
            _device['permission'] == 'denied')) {
      return const SizedBox.shrink();
    }
    final canEnable =
        status?['enabled'] == true &&
        _device['supported'] == true &&
        _device['needs_install'] != true &&
        _device['permission'] != 'denied';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
              _copy('Training notifications', 'إشعارات التدريب'),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (widget.compact)
              Text(
                _copy(
                  'Keep a little encouragement close, with reminders and updates from your coach.',
                  'احصل على بعض التشجيع مع تذكيرات التدريب وتحديثات مدربك.',
                ),
              ),
            if (_failed) ...<Widget>[
              Text(
                _copy(
                  'Could not save or load notifications. Please retry.',
                  'تعذّر حفظ الإشعارات أو تحميلها. أعد المحاولة.',
                ),
              ),
              TextButton(
                onPressed: _busy ? null : _load,
                child: Text(_copy('Retry', 'إعادة المحاولة')),
              ),
            ],
            if (status == null && !_failed) const LinearProgressIndicator(),
            if (_device['needs_install'] == true)
              Text(
                _copy(
                  'On iPhone, add MAYOS to your Home Screen and open it there. Notifications need iOS 16.4 or later.',
                  'على iPhone، أضف MAYOS إلى الشاشة الرئيسية وافتحه منها. تتطلب الإشعارات iOS 16.4 أو أحدث.',
                ),
              )
            else if (_device['permission'] == 'denied')
              Text(
                _copy(
                  'Notifications are blocked. In your browser or device settings, allow notifications for MAYOS, then return here.',
                  'الإشعارات محظورة. اسمح بإشعارات MAYOS من إعدادات المتصفح أو الجهاز، ثم عد إلى هنا.',
                ),
              )
            else if (_device['supported'] != true)
              Text(
                _copy(
                  'This browser does not support push notifications.',
                  'هذا المتصفح لا يدعم الإشعارات.',
                ),
              )
            else if (status != null && status['enabled'] != true)
              Text(
                _copy(
                  'Notifications are temporarily unavailable.',
                  'الإشعارات غير متاحة مؤقتًا.',
                ),
              ),
            if (subscribed)
              TextButton(
                onPressed: _busy ? null : _disable,
                child: Text(
                  _copy('Turn off on this device', 'إيقاف على هذا الجهاز'),
                ),
              )
            else if (canEnable)
              FilledButton(
                onPressed: _busy ? null : _enable,
                child: Text(_copy('Turn on', 'تشغيل')),
              ),
            if (widget.compact)
              TextButton(
                onPressed: _dismiss,
                child: Text(_copy('Not now', 'ليس الآن')),
              ),
            if (!widget.compact && status != null) ...<Widget>[
              for (final item in <(String, String, String)>[
                ('workout_reminders', 'Workout reminders', 'تذكيرات التدريب'),
                ('alerts', 'Alerts', 'التنبيهات'),
                ('coach_updates', 'Coach updates', 'تحديثات المدرب'),
              ])
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(_copy(item.$2, item.$3)),
                  value: _prefs[item.$1] == true,
                  onChanged: _busy ? null : (value) => _save(item.$1, value),
                ),
              for (final item in <(String, String, String)>[
                ('reminder_time', 'Reminder time', 'وقت التذكير'),
                ('quiet_start', 'Quiet hours start', 'بداية ساعات الهدوء'),
                ('quiet_end', 'Quiet hours end', 'نهاية ساعات الهدوء'),
              ])
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(_copy(item.$2, item.$3)),
                  trailing: Text(_prefs[item.$1] as String),
                  onTap: _busy ? null : () => _time(item.$1),
                ),
              Text(
                _copy(
                  'Timezone: ${_prefs['timezone']}. Set training days in Profile.',
                  'المنطقة الزمنية: ${_prefs['timezone']}. حدد أيام التدريب في الملف الشخصي.',
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
