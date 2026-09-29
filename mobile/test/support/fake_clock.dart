class FakeClock {
  FakeClock(this._currentTime);

  DateTime _currentTime;

  DateTime call() => _currentTime;

  void advance(Duration duration) {
    _currentTime = _currentTime.add(duration);
  }
}
