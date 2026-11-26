import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../core/api/api_client.dart';
import '../data/event_repository.dart';
import '../data/event_updates.dart';

class EventDetailModel extends ChangeNotifier {
  EventDetailModel(this.identifier, this.repository, this.updates);
  final String identifier;
  final EventRepository repository;
  final EventUpdates updates;
  EventRecord? event;
  String? error;
  bool loading = false;
  bool mutating = false;
  bool _disposed = false;
  bool _active = true;
  int _epoch = 0;
  bool _queued = false;
  StreamSubscription<int>? _subscription;
  ApiCancellation? _operation;

  void start() {
    if (_disposed) return;
    _active = true;
    unawaited(reload());
    _subscription ??= updates
        .watch(identifier)
        .listen(
          (_) {
            unawaited(reload());
          },
          onError: (Object failure) {
            if (_disposed) return;
            if (failure is ApiFailure &&
                {401, 403, 404}.contains(failure.status)) {
              _epoch++;
              _operation?.cancel();
              loading = false;
              _queued = false;
              event = null;
            }
            error = failure is ApiFailure
                ? failure.message
                : 'Atualização temporariamente indisponível.';
            notifyListeners();
          },
        );
  }

  Future<void> reload() async {
    if (_disposed || !_active) return;
    if (loading) {
      _queued = true;
      return;
    }
    loading = true;
    final epoch = _epoch;
    final operation = ApiCancellation();
    _operation = operation;
    error = null;
    notifyListeners();
    try {
      final record = await repository.detail(
        identifier,
        cancellation: operation,
      );
      if (!_disposed && _active && epoch == _epoch) event = record;
    } on ApiFailure catch (failure) {
      if (!_disposed && _active && epoch == _epoch) {
        error = failure.message;
        if ({401, 403, 404}.contains(failure.status)) event = null;
      }
    } on Exception {
      if (!_disposed && _active && epoch == _epoch) {
        error = 'Não foi possível carregar o encontro.';
      }
    } finally {
      if (!_disposed && _active && epoch == _epoch) {
        loading = false;
        notifyListeners();
        if (_queued) {
          _queued = false;
          unawaited(reload());
        }
      }
    }
  }

  Future<void> cancel() async {
    final previous = event;
    if (_disposed || previous == null || mutating) return;
    mutating = true;
    error = null;
    notifyListeners();
    try {
      final saved = await repository.cancel(previous);
      if (!_disposed) event = saved;
    } on ApiFailure catch (failure) {
      if (!_disposed) error = failure.message;
    } on Exception {
      if (!_disposed) error = 'Não foi possível cancelar o encontro.';
    } finally {
      if (!_disposed) {
        mutating = false;
        notifyListeners();
      }
    }
  }

  void suspend() {
    _active = false;
    _operation?.cancel();
    _epoch++;
    loading = false;
    _queued = false;
    unawaited(_subscription?.cancel());
    _subscription = null;
    event = null;
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _operation?.cancel();
    unawaited(_subscription?.cancel());
    _subscription = null;
    super.dispose();
  }
}
