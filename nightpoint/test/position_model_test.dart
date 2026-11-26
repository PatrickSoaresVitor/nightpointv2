import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:nightpoint/core/location/device_location.dart';
import 'package:nightpoint/features/events/presentation/position_model.dart';

class FakeLocation implements DeviceLocation {
  final stream = StreamController<DevicePoint>.broadcast();
  Future<DevicePoint> Function() locate = () async =>
      const DevicePoint(-20.5, -47.4);
  @override
  Future<DevicePoint> current() => locate();
  @override
  Stream<DevicePoint> watch() => stream.stream;
}

void main() {
  test(
    'denied location leaves manual search available and no watcher',
    () async {
      final device = FakeLocation()
        ..locate = () async => throw const LocationUnavailable(
          'Permissão negada. Use localização manual.',
        );
      final model = PositionModel(device);
      await model.start();
      expect(model.point, isNull);
      expect(model.error, contains('manual'));
      expect(device.stream.hasListener, isFalse);
      model.dispose();
      await device.stream.close();
    },
  );
  test('position updates locally and stop cancels and clears it', () async {
    final device = FakeLocation();
    final model = PositionModel(device);
    await model.start();
    expect(model.point!.latitude, -20.5);
    device.stream.add(const DevicePoint(-20.51, -47.41));
    await Future<void>.delayed(Duration.zero);
    expect(model.point!.latitude, -20.51);
    model.stop();
    expect(model.point, isNull);
    expect(device.stream.hasListener, isFalse);
    model.dispose();
    await device.stream.close();
  });
  test('background/disposal invalidates pending device response', () async {
    final pending = Completer<DevicePoint>();
    final device = FakeLocation()..locate = () => pending.future;
    final model = PositionModel(device);
    final task = model.start();
    await Future<void>.delayed(Duration.zero);
    model.stop();
    pending.complete(const DevicePoint(1, 1));
    await task;
    expect(model.point, isNull);
    expect(device.stream.hasListener, isFalse);
    model.dispose();
    await device.stream.close();
  });
}
