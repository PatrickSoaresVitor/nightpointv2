import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nightpoint/core/api/api_client.dart';
import 'package:nightpoint/features/events/data/event_repository.dart';
import 'package:nightpoint/features/events/presentation/map_model.dart';

Map<String, Object?> event(String id, {String visibility = 'listed'}) => {
  'id': id,
  'title': id,
  'category_code': 'meet',
  'starts_at': '2026-12-01T12:00:00Z',
  'location_label': 'Ponto fictício',
  'version': 1,
  'longitude': 0.01,
  'latitude': 0.01,
  'state': 'published',
  'visibility': visibility,
};

void main() {
  test(
    'map reauthorizes detail and omits events made private after discovery',
    () async {
      final session = ApiSession()..signIn('test');
      final client = MockClient((request) async {
        if (request.url.path.endsWith('/nearby')) {
          return http.Response(
            jsonEncode({
              'items': [event('visible'), event('hidden'), event('changed')],
              'next_cursor': 'more',
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/hidden')) {
          return http.Response('{}', 404);
        }
        return http.Response(
          jsonEncode(
            event(
              request.url.pathSegments.last,
              visibility: request.url.path.endsWith('/changed')
                  ? 'owner_only'
                  : 'listed',
            ),
          ),
          200,
        );
      });
      final api = ApiClient(
        ApiConfiguration('http://127.0.0.1:8000'),
        session,
        transport: client,
      );
      final model = MapModel(EventRepository(api));
      await model.load();
      expect(model.items.map((item) => item.id), ['visible']);
      expect(model.truncated, isTrue);
      model.suspend();
      expect(model.items, isEmpty);
      model.dispose();
      api.close();
      session.dispose();
    },
  );

  test('suspension discards a late geographic response', () async {
    final response = Completer<http.Response>();
    final session = ApiSession()..signIn('test');
    final api = ApiClient(
      ApiConfiguration('http://127.0.0.1:8000'),
      session,
      transport: MockClient((_) => response.future),
    );
    final model = MapModel(EventRepository(api));
    final pending = model.load();
    model.suspend();
    response.complete(
      http.Response(
        jsonEncode({
          'items': [event('late')],
          'next_cursor': null,
        }),
        200,
      ),
    );
    await pending;
    expect(model.items, isEmpty);
    expect(model.loading, isFalse);
    model.dispose();
    api.close();
    session.dispose();
  });
}
