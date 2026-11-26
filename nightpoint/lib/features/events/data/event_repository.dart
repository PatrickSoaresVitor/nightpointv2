import '../../../core/api/api_client.dart';

import '../models/event_record.dart';
export '../models/event_record.dart';

class EventRepository {
  const EventRepository(this.api);
  final ApiClient api;

  Future<EventRecord> detail(
    String identifier, {
    ApiCancellation? cancellation,
  }) async {
    final response = await api.request(
      'GET',
      '/api/v1/events/${Uri.encodeComponent(identifier)}',
      cancellation: cancellation,
    );
    return EventRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<EventRecord> create(
    Map<String, Object?> values,
    String idempotencyKey,
  ) async {
    final response = await api.request(
      'POST',
      '/api/v1/events',
      body: values,
      headers: {'Idempotency-Key': idempotencyKey},
    );
    return EventRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<EventRecord> update(
    EventRecord previous,
    Map<String, Object?> values,
  ) async {
    final response = await api.request(
      'PUT',
      '/api/v1/events/${Uri.encodeComponent(previous.id)}',
      body: values,
      headers: {'If-Match': '"${previous.version}"'},
    );
    return EventRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<EventRecord> cancel(EventRecord previous) async {
    final response = await api.request(
      'POST',
      '/api/v1/events/${Uri.encodeComponent(previous.id)}/cancel',
      headers: {'If-Match': '"${previous.version}"'},
    );
    return EventRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<OwnedEventPage> owned({
    int offset = 0,
    ApiCancellation? cancellation,
  }) async {
    // Query parameters are built here; callers never supply a full URL/origin.
    final response = await api.request(
      'GET',
      '/api/v1/me/events',
      query: {'offset': '$offset'},
      cancellation: cancellation,
    );
    final json = response.data as Map<String, dynamic>;
    return OwnedEventPage(
      (json['items'] as List<dynamic>)
          .map((item) => EventRecord.fromJson(item as Map<String, dynamic>))
          .toList(),
      json['next_offset'] as int?,
    );
  }

  Future<EventPage> nearby({
    required double longitude,
    required double latitude,
    required DateTime from,
    required DateTime until,
    double radius = 10000,
    String? category,
    String? cursor,
    ApiCancellation? cancellation,
  }) async {
    final query = <String, Object?>{
      'longitude': longitude,
      'latitude': latitude,
      'radius_m': radius,
      'from_ts': from.toUtc().toIso8601String(),
      'until_ts': until.toUtc().toIso8601String(),
      'limit': 25,
    };
    if (category != null) query['category_code'] = category;
    if (cursor != null) query['cursor'] = cursor;
    final response = await api.request(
      'POST',
      '/api/v1/discovery/nearby',
      body: query,
      cancellation: cancellation,
    );
    final json = response.data as Map<String, dynamic>;
    return EventPage(
      (json['items'] as List<dynamic>)
          .map((item) => EventRecord.fromJson(item as Map<String, dynamic>))
          .toList(),
      json['next_cursor'] as String?,
    );
  }
}
