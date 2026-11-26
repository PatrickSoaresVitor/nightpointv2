import 'package:flutter/foundation.dart';

import '../../../core/api/api_client.dart';
import '../data/event_repository.dart';

/// A bounded projection: every marker is reauthorized by the detail endpoint.
class MapModel extends ChangeNotifier {
  MapModel(this.repository);
  final EventRepository repository;
  List<EventRecord> items = [];
  bool loading = false, truncated = false;
  String? error;
  double latitude = 0, longitude = 0;
  int _epoch = 0;
  bool _disposed = false;
  ApiCancellation? _operation;

  Future<void> load({double? lat, double? lon}) async {
    if (_disposed || (loading && lat == null && lon == null)) return;
    latitude = lat ?? latitude;
    longitude = lon ?? longitude;
    _operation?.cancel();
    final operation = _operation = ApiCancellation();
    final epoch = ++_epoch;
    loading = true;
    error = null;
    // Clear stale coordinates immediately, including on loss of authorization.
    items = [];
    notifyListeners();
    try {
      final from = DateTime.now().toUtc().subtract(const Duration(days: 1));
      final page = await repository.nearby(
        longitude: longitude,
        latitude: latitude,
        radius: 10000,
        from: from,
        until: from.add(const Duration(days: 30)),
        cancellation: operation,
      );
      final markers = <EventRecord>[];
      for (final summary in page.items.take(25)) {
        if (_disposed || epoch != _epoch) return;
        try {
          final detail = await repository.detail(
            summary.id,
            cancellation: operation,
          );
          if (detail.state == 'published' &&
              detail.visibility == 'listed' &&
              detail.latitude != null &&
              detail.longitude != null) {
            markers.add(detail);
          }
        } on ApiFailure catch (failure) {
          if (failure.status != 404 && failure.status != 403) rethrow;
          // An event made private after discovery never becomes a marker.
        }
      }
      if (_disposed || epoch != _epoch) return;
      items = List.unmodifiable(markers);
      truncated = page.nextCursor != null;
    } on ApiFailure catch (failure) {
      if (!_disposed && epoch == _epoch) error = failure.message;
    } on Exception {
      if (!_disposed && epoch == _epoch) {
        error = 'Não foi possível atualizar o mapa.';
      }
    } finally {
      if (!_disposed && epoch == _epoch) {
        loading = false;
        notifyListeners();
      }
    }
  }

  void suspend() {
    _epoch++;
    _operation?.cancel();
    items = [];
    loading = false;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _operation?.cancel();
    super.dispose();
  }
}
