import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../core/api/api_client.dart';
import '../data/event_repository.dart';

class EventsModel extends ChangeNotifier {
  EventsModel(this.repository) {
    from = DateTime.now().toUtc().subtract(const Duration(days: 1));
  }
  final EventRepository repository;
  final List<EventRecord> _items = [];
  List<EventRecord> get items => List.unmodifiable(_items);
  bool owned = false, loading = false, hasMore = false;
  String? error, category;
  double longitude = -47.4009, latitude = -20.5386, radius = 10000;
  late DateTime from;
  String? _cursor;
  int _offset = 0, _epoch = 0;
  bool _disposed = false;
  ApiCancellation? _operation;

  void changeMode(bool value) {
    if (value == owned) return;
    owned = value;
    unawaited(load(reset: true));
  }

  void configure({
    required double lon,
    required double lat,
    required double radiusM,
    required DateTime start,
    String? categoryCode,
  }) {
    longitude = lon;
    latitude = lat;
    radius = radiusM;
    from = start.toUtc();
    category = categoryCode;
    unawaited(load(reset: true));
  }

  Future<void> load({bool reset = false}) async {
    if (_disposed) return;
    if (reset) {
      _operation?.cancel();
      _epoch++;
      _items.clear();
      _cursor = null;
      _offset = 0;
    } else if (loading || !hasMore) {
      return;
    }
    final epoch = _epoch;
    final operation = ApiCancellation();
    _operation = operation;
    loading = true;
    error = null;
    notifyListeners();
    try {
      if (owned) {
        final page = await repository.owned(
          offset: _offset,
          cancellation: operation,
        );
        if (_disposed || epoch != _epoch) return;
        _items.addAll(page.items);
        hasMore = page.nextOffset != null;
        _offset = page.nextOffset ?? 0;
      } else {
        final page = await repository.nearby(
          longitude: longitude,
          latitude: latitude,
          radius: radius,
          from: from,
          until: from.add(const Duration(days: 30)),
          category: category,
          cursor: _cursor,
          cancellation: operation,
        );
        if (_disposed || epoch != _epoch) return;
        _items.addAll(page.items);
        _cursor = page.nextCursor;
        hasMore = _cursor != null;
      }
    } on ApiFailure catch (failure) {
      if (!_disposed && epoch == _epoch) error = failure.message;
    } on Exception {
      if (!_disposed && epoch == _epoch) {
        error = 'Não foi possível carregar os encontros.';
      }
    } finally {
      if (!_disposed && epoch == _epoch) {
        loading = false;
        notifyListeners();
      }
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _operation?.cancel();
    super.dispose();
  }
}
