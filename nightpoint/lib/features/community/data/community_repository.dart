import '../../../core/api/api_client.dart';
import '../models/community_record.dart';
export '../models/community_record.dart';

class CommunityRepository {
  const CommunityRepository(this.api);
  final ApiClient api;
  String _path(String eventId) =>
      '/api/v1/events/${Uri.encodeComponent(eventId)}/community';

  Future<CommunitySummary> summary(
    String eventId, {
    ApiCancellation? cancellation,
  }) async {
    final response = await api.request(
      'GET',
      _path(eventId),
      cancellation: cancellation,
    );
    return CommunitySummary.fromJson(response.data as Map<String, dynamic>);
  }

  Future<void> reaction(String eventId, String kind, bool active) async {
    if (!{'like', 'participation'}.contains(kind)) {
      throw ArgumentError('Interação inválida');
    }
    await api.request(
      'PUT',
      '${_path(eventId)}/reactions/$kind',
      body: {'active': active},
    );
  }

  Future<CommentPage> comments(
    String eventId, {
    int offset = 0,
    ApiCancellation? cancellation,
  }) async {
    final response = await api.request(
      'GET',
      '${_path(eventId)}/comments',
      query: {'offset': '$offset', 'include_removed': 'true'},
      cancellation: cancellation,
    );
    final json = response.data as Map<String, dynamic>;
    return CommentPage(
      (json['items'] as List<dynamic>)
          .map((item) => CommentRecord.fromJson(item as Map<String, dynamic>))
          .toList(),
      json['next_offset'] as int?,
    );
  }

  Future<CommentRecord> comment(String eventId, String text, String key) async {
    final response = await api.request(
      'POST',
      '${_path(eventId)}/comments',
      body: {'text': text},
      headers: {'Idempotency-Key': key},
    );
    return CommentRecord.fromJson(response.data as Map<String, dynamic>);
  }

  Future<void> visibility(
    String eventId,
    CommentRecord previous,
    bool removed,
  ) async {
    await api.request(
      'PUT',
      '${_path(eventId)}/comments/${Uri.encodeComponent(previous.id)}/visibility',
      body: {'removed': removed},
      headers: {'If-Match': '"${previous.version}"'},
    );
  }
}
