import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nightpoint/core/api/api_client.dart';
import 'package:nightpoint/features/events/data/event_updates.dart';

void main() {
  test(
    'SSE emits resync and newer versions, skips duplicates, sends bearer only in header',
    () async {
      final session = ApiSession()..signIn('synthetic-token');
      final updates = EventUpdates(
        ApiConfiguration('http://127.0.0.1:8000'),
        session,
        transport: () => MockClient((request) async {
          expect(request.headers['Authorization'], 'Bearer synthetic-token');
          expect(request.url.query, isEmpty);
          return http.Response(
            'event: resync\ndata: {"version":1}\n\n'
            'event: changed\ndata: {"version":1}\n\n'
            'event: changed\ndata: {"version":2}\n\n',
            200,
            headers: {'content-type': 'text/event-stream'},
          );
        }),
      );
      expect(await updates.watch('synthetic-event').take(2).toList(), [1, 2]);
    },
  );

  test(
    'lease expiry revalidates and only HTTP 401 clears memory session',
    () async {
      var attempts = 0;
      final session = ApiSession()..signIn('synthetic-token');
      final updates = EventUpdates(
        ApiConfiguration('http://localhost:8000'),
        session,
        transport: () => MockClient((_) async {
          attempts++;
          expect(session.signedIn, true);
          if (attempts == 1) {
            return http.Response(
              'event: session-expired\ndata: {}\n\n',
              200,
              headers: {'content-type': 'text/event-stream'},
            );
          }
          return http.Response('', 401);
        }),
      );
      expect(await updates.watch('synthetic-event').toList(), isEmpty);
      expect(session.signedIn, false);
      expect(attempts, 2);
    },
  );

  test(
    'forbidden resource stops without reconnecting or revealing server content',
    () async {
      var attempts = 0;
      final session = ApiSession()..signIn('synthetic-token');
      final updates = EventUpdates(
        ApiConfiguration('http://localhost:8000'),
        session,
        transport: () => MockClient((_) async {
          attempts++;
          return http.Response('private-sentinel', 404);
        }),
      );
      await expectLater(
        updates.watch('hidden'),
        emitsInOrder([
          emitsError(isA<ApiFailure>().having((e) => e.status, 'status', 404)),
          emitsDone,
        ]),
      );
      expect(attempts, 1);
    },
  );
}
