import 'package:flutter/foundation.dart';
import '../../../core/api/api_client.dart';
import '../data/garage_repository.dart';

class VehicleDetailModel extends ChangeNotifier {
  VehicleDetailModel(this.repository, this.identifier);
  final GarageRepository repository;
  final String identifier;
  VehicleRecord? vehicle;
  List<VehicleRevision> history = [];
  bool loading = false, saving = false;
  String? error;
  bool _disposed = false;
  int _epoch = 0;
  ApiCancellation? _operation;

  Future<void> load() async {
    _operation?.cancel();
    final cancellation = _operation = ApiCancellation();
    final epoch = ++_epoch;
    loading = true;
    error = null;
    vehicle = null;
    history = [];
    notifyListeners();
    try {
      final current = await repository.detail(
        identifier,
        cancellation: cancellation,
      );
      final revisions = await repository.history(
        identifier,
        cancellation: cancellation,
      );
      if (_disposed || epoch != _epoch) return;
      vehicle = current;
      history = revisions;
    } on ApiFailure catch (failure) {
      if (!_disposed && epoch == _epoch) error = failure.message;
    } on Exception {
      if (!_disposed && epoch == _epoch) {
        error = 'Não foi possível consultar o veículo.';
      }
    } finally {
      if (!_disposed && epoch == _epoch) {
        loading = false;
        notifyListeners();
      }
    }
  }

  Future<void> change({bool? primary, bool? archived}) async {
    final previous = vehicle;
    if (previous == null || saving || loading || _disposed) return;
    saving = true;
    error = null;
    notifyListeners();
    try {
      await repository.update(
        previous,
        previous.values(
          isPrimary: archived == true ? false : primary,
          isArchived: archived,
        ),
      );
      if (!_disposed) await load();
    } on ApiFailure catch (failure) {
      if (!_disposed) {
        error = failure.status == 412
            ? 'O veículo mudou. Atualize os dados antes de tentar novamente.'
            : failure.message;
      }
    } on Exception {
      if (!_disposed) error = 'Não foi possível atualizar o veículo.';
    } finally {
      if (!_disposed) {
        saving = false;
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
