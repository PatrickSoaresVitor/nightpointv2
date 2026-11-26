import 'dart:async';
import 'package:flutter/foundation.dart';
import '../../../core/api/api_client.dart';
import '../../../core/api/idempotency_key.dart';
import '../../events/data/event_updates.dart';
import '../data/community_repository.dart';

class CommunityModel extends ChangeNotifier {
  CommunityModel(this.repository, this.eventId, this.updates);
  final CommunityRepository repository;
  final String eventId;
  final EventUpdates updates;
  CommunitySummary? summary;
  final List<CommentRecord> comments = [];
  bool loading = false, saving = false, hasMore = false;
  String? error, _commentKey, _commentText;
  int _offset = 0, _epoch = 0;
  bool _disposed = false, _active = false, _queued = false;
  ApiCancellation? _operation;
  StreamSubscription<int>? _subscription;

  void start() {
    if (_disposed) return;
    _active = true;
    unawaited(load());
    _subscription ??= updates
        .watch(eventId)
        .listen(
          (_) {
            if (!saving && !loading) unawaited(load());
          },
          onError: (Object failure) {
            if (_disposed || !_active) return;
            if (failure is ApiFailure &&
                {401, 403, 404}.contains(failure.status)) {
              _epoch++;
              _operation?.cancel();
              summary = null;
              comments.clear();
              loading = false;
            }
            error = failure is ApiFailure
                ? failure.message
                : 'Atualização temporariamente indisponível.';
            notifyListeners();
          },
        );
  }

  Future<void> load({bool reset = true}) async {
    if (_disposed || !_active) return;
    if (loading) {
      _queued = reset;
      return;
    }
    final offset = reset ? 0 : _offset;
    final epoch = _epoch;
    final cancellation = _operation = ApiCancellation();
    loading = true;
    error = null;
    notifyListeners();
    try {
      final current = await repository.summary(
        eventId,
        cancellation: cancellation,
      );
      final page = await repository.comments(
        eventId,
        offset: offset,
        cancellation: cancellation,
      );
      if (_disposed || !_active || epoch != _epoch) return;
      if (reset) comments.clear();
      summary = current;
      comments.addAll(page.items);
      hasMore = page.nextOffset != null;
      _offset = page.nextOffset ?? 0;
    } on ApiFailure catch (failure) {
      if (!_disposed && _active && epoch == _epoch) {
        error = failure.message;
        if ({401, 403, 404}.contains(failure.status)) {
          summary = null;
          comments.clear();
        }
      }
    } on Exception {
      if (!_disposed && _active && epoch == _epoch) {
        error = 'Não foi possível carregar as interações.';
      }
    } finally {
      if (!_disposed && _active && epoch == _epoch) {
        loading = false;
        notifyListeners();
        if (_queued) {
          _queued = false;
          unawaited(load());
        }
      }
    }
  }

  Future<bool> _write(Future<void> Function() operation) async {
    if (_disposed || !_active || saving || loading) return false;
    saving = true;
    error = null;
    notifyListeners();
    try {
      await operation();
      if (!_disposed && _active) await load();
      return true;
    } on ApiFailure catch (failure) {
      if (!_disposed) {
        error = failure.status == 412
            ? 'O comentário mudou. Atualize antes de tentar novamente.'
            : failure.message;
      }
      return false;
    } on Exception {
      if (!_disposed) error = 'Não foi possível salvar a interação.';
      return false;
    } finally {
      if (!_disposed) {
        saving = false;
        notifyListeners();
      }
    }
  }

  Future<bool> react(String kind, bool active) =>
      _write(() => repository.reaction(eventId, kind, active));
  Future<bool> visibility(CommentRecord comment, bool removed) =>
      _write(() => repository.visibility(eventId, comment, removed));
  Future<bool> send(String text) async {
    final value = text.trim();
    if (value.isEmpty || value.length > 1000) return false;
    if (_commentText != value) {
      _commentKey = newIdempotencyKey();
      _commentText = value;
    }
    final saved = await _write(() async {
      await repository.comment(eventId, value, _commentKey!);
    });
    if (saved) {
      _commentKey = null;
      _commentText = null;
    }
    return saved;
  }

  void suspend() {
    _active = false;
    _epoch++;
    _operation?.cancel();
    unawaited(_subscription?.cancel());
    _subscription = null;
    summary = null;
    comments.clear();
    loading = false;
    _queued = false;
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _operation?.cancel();
    unawaited(_subscription?.cancel());
    super.dispose();
  }
}
