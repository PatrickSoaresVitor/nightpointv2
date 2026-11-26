import '../../../core/api/api_client.dart';
import '../models/vehicle_record.dart';
export '../models/vehicle_record.dart';

class GarageRepository {
  const GarageRepository(this.api);
  final ApiClient api;
  static const _path = '/api/v1/me/vehicles';

  Future<VehiclePage> owned({
    bool archived = false,
    int offset = 0,
    ApiCancellation? cancellation,
  }) async {
    final response = await api.request(
      'GET',
      _path,
      query: {'archived': '$archived', 'offset': '$offset'},
      cancellation: cancellation,
    );
    final json = response.data as Map<String, dynamic>;
    return VehiclePage(
      (json['items'] as List<dynamic>)
          .map((item) => VehicleRecord.fromJson(item as Map<String, dynamic>))
          .toList(),
      json['next_offset'] as int?,
    );
  }

  Future<VehicleRecord> detail(
    String id, {
    ApiCancellation? cancellation,
  }) async {
    final response = await api.request(
      'GET',
      '$_path/${Uri.encodeComponent(id)}',
      cancellation: cancellation,
    );
    return VehicleRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<VehicleRecord> create(Map<String, Object?> values, String key) async {
    final response = await api.request(
      'POST',
      _path,
      body: values,
      headers: {'Idempotency-Key': key},
    );
    return VehicleRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<VehicleRecord> update(
    VehicleRecord previous,
    Map<String, Object?> values,
  ) async {
    final response = await api.request(
      'PUT',
      '$_path/${Uri.encodeComponent(previous.id)}',
      body: values,
      headers: {'If-Match': '"${previous.version}"'},
    );
    return VehicleRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<List<VehicleRevision>> history(
    String id, {
    ApiCancellation? cancellation,
  }) async {
    final response = await api.request(
      'GET',
      '$_path/${Uri.encodeComponent(id)}/history',
      query: {'limit': '25'},
      cancellation: cancellation,
    );
    return ((response.data as Map<String, dynamic>)['items'] as List<dynamic>)
        .map((item) => VehicleRevision.fromJson(item as Map<String, dynamic>))
        .toList();
  }
}
