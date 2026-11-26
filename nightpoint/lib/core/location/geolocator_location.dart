import 'package:geolocator/geolocator.dart';
import 'device_location.dart';

/// Device capability only: no API client, persistence or location logging.
class GeolocatorLocation implements DeviceLocation {
  @override
  Future<DevicePoint> current() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw const LocationUnavailable(
        'Localização desativada. Use a localização manual.',
      );
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      throw const LocationUnavailable(
        'Permissão de localização negada. Use a localização manual.',
      );
    }
    final point = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.medium,
        timeLimit: Duration(seconds: 15),
      ),
    );
    return DevicePoint(point.latitude, point.longitude);
  }

  @override
  Stream<DevicePoint> watch() => Geolocator.getPositionStream(
    locationSettings: const LocationSettings(
      accuracy: LocationAccuracy.medium,
      distanceFilter: 25,
    ),
  ).map((point) => DevicePoint(point.latitude, point.longitude));
}
