import 'dart:async';
import 'package:flutter/foundation.dart';
import '../../../core/location/device_location.dart';

class PositionModel extends ChangeNotifier {
  PositionModel(this.device);
  final DeviceLocation device;
  DevicePoint? point;
  String? error;
  bool busy = false;
  int _epoch = 0;
  bool _disposed = false;
  StreamSubscription<DevicePoint>? _subscription;

  Future<void> start() async {
    if (busy || _disposed) return;
    final epoch = ++_epoch;
    await _subscription?.cancel();
    if (_disposed || epoch != _epoch) return;
    busy = true;
    error = null;
    notifyListeners();
    try {
      final current = await device.current();
      if (_disposed || epoch != _epoch) return;
      if (!current.valid) {
        throw const LocationUnavailable(
          'Localização fora da área suportada pelo mapa.',
        );
      }
      point = current;
      _subscription = device.watch().listen(
        (next) {
          if (_disposed || epoch != _epoch || !next.valid) return;
          point = next;
          notifyListeners();
        },
        onError: (Object _) {
          if (_disposed || epoch != _epoch) return;
          error =
              'Atualização da posição indisponível. Use a localização manual.';
          unawaited(_subscription?.cancel());
          _subscription = null;
          notifyListeners();
        },
      );
    } on LocationUnavailable catch (failure) {
      if (!_disposed && epoch == _epoch) error = failure.message;
    } on Exception {
      if (!_disposed && epoch == _epoch) {
        error =
            'Localização indisponível ou demorou a responder. Use a localização manual.';
      }
    } finally {
      if (!_disposed && epoch == _epoch) {
        busy = false;
        notifyListeners();
      }
    }
  }

  void stop() {
    _epoch++;
    unawaited(_subscription?.cancel());
    _subscription = null;
    point = null;
    busy = false;
    error = null;
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    stop();
    super.dispose();
  }
}
