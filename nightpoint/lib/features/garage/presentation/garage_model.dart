import 'package:flutter/foundation.dart';
import '../../../core/api/api_client.dart';
import '../data/garage_repository.dart';

class GarageModel extends ChangeNotifier {
  GarageModel(this.repository);
  final GarageRepository repository;
  final List<VehicleRecord> items = [];
  bool loading = false, archived = false, hasMore = false;
  String? error;
  int _offset = 0, _epoch = 0;
  bool _disposed = false;
  ApiCancellation? _operation;

  Future<void> load({bool reset = true, bool? showArchived}) async {
    if (_disposed || loading && !reset) return;
    if (reset) {
      _operation?.cancel();
      _epoch++;
      items.clear();
      _offset = 0;
    }
    archived = showArchived ?? archived;
    final epoch = _epoch;
    final cancellation = _operation = ApiCancellation();
    loading = true;
    error = null;
    notifyListeners();
    try {
      final page = await repository.owned(
        archived: archived,
        offset: _offset,
        cancellation: cancellation,
      );
      if (_disposed || epoch != _epoch) return;
      items.addAll(page.items);
      hasMore = page.nextOffset != null;
      _offset = page.nextOffset ?? 0;
    } on ApiFailure catch (failure) {
      if (!_disposed && epoch == _epoch) error = failure.message;
    } on Exception {
      if (!_disposed && epoch == _epoch) {
        error = 'Não foi possível carregar sua garagem.';
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
