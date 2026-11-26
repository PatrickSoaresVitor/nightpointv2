class DevicePoint {
  const DevicePoint(this.latitude, this.longitude);
  final double latitude, longitude;
  bool get valid =>
      latitude.isFinite &&
      longitude.isFinite &&
      latitude.abs() <= 85 &&
      longitude.abs() <= 180;
}

class LocationUnavailable implements Exception {
  const LocationUnavailable(this.message);
  final String message;
}

abstract interface class DeviceLocation {
  Future<DevicePoint> current();
  Stream<DevicePoint> watch();
}
