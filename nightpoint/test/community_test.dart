import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nightpoint/core/api/api_client.dart';
import 'package:nightpoint/features/community/data/community_repository.dart';
import 'package:nightpoint/features/community/presentation/community_model.dart';
import 'package:nightpoint/features/events/data/event_updates.dart';

class ControlledUpdates extends EventUpdates {
  ControlledUpdates(super.configuration, super.session);
  final controller = StreamController<int>.broadcast();
  @override
  Stream<int> watch(String eventId) => controller.stream;
}

Future<void> until(CommunityModel model, bool Function() predicate) async {
  final done = Completer<void>();
  void changed() {
    if (predicate() && !done.isCompleted) done.complete();
  }

  model.addListener(changed);
  changed();
  try {
    await done.future.timeout(const Duration(seconds: 3));
  } finally {
    model.removeListener(changed);
  }
}

const summary = {
  'likes': 0,
  'participants': 0,
  'liked': false,
  'participating': false,
};
const comment = {
  'id': 'synthetic-comment',
  'text': 'Synthetic',
  'version': 1,
  'mine': true,
  'organizer': false,
  'removed': false,
  'can_remove': true,
  'can_restore': false,
};

void main() {
  test(
    'SSE invalidation reauthorizes community and clears inaccessible data',
    () async {
      final session = ApiSession()..signIn('synthetic');
      final configuration = ApiConfiguration('http://127.0.0.1:8000');
      var reads = 0;
      final api = ApiClient(
        configuration,
        session,
        transport: MockClient((request) async {
          if (request.url.path.endsWith('/comments')) {
            expect(request.url.queryParameters['include_removed'], 'true');
            return http.Response(
              jsonEncode({
                'items': [comment],
                'next_offset': null,
              }),
              200,
            );
          }
          reads++;
          return http.Response(
            jsonEncode(reads == 1 ? summary : {}),
            reads == 1 ? 200 : 404,
          );
        }),
      );
      final updates = ControlledUpdates(configuration, session);
      final model = CommunityModel(
        CommunityRepository(api),
        'synthetic-event',
        updates,
      )..start();
      await until(model, () => !model.loading && model.summary != null);
      expect(model.comments.single.text, 'Synthetic');
      updates.controller.add(1);
      await until(model, () => reads == 2 && !model.loading);
      expect(model.summary, isNull);
      expect(model.comments, isEmpty);
      expect(model.error, isNotNull);
      model.dispose();
      await updates.controller.close();
      api.close();
      session.dispose();
    },
  );

  test(
    'uncertain comment retry keeps key and never accepts forged author fields',
    () async {
      final session = ApiSession()..signIn('synthetic');
      final configuration = ApiConfiguration('http://127.0.0.1:8000');
      final keys = <String?>[];
      final api = ApiClient(
        configuration,
        session,
        transport: MockClient((request) async {
          if (request.method == 'POST') {
            keys.add(request.headers['Idempotency-Key']);
            expect(jsonDecode(request.body), {'text': 'Synthetic'});
            return http.Response(
              jsonEncode(keys.length == 1 ? {} : comment),
              keys.length == 1 ? 503 : 201,
            );
          }
          return http.Response(
            jsonEncode(
              request.url.path.endsWith('/comments')
                  ? {'items': [], 'next_offset': null}
                  : summary,
            ),
            200,
          );
        }),
      );
      final updates = ControlledUpdates(configuration, session);
      final model = CommunityModel(
        CommunityRepository(api),
        'synthetic-event',
        updates,
      )..start();
      await until(model, () => !model.loading && model.summary != null);
      expect(await model.send('Synthetic'), isFalse);
      expect(await model.send('Synthetic'), isTrue);
      expect(keys.length, 2);
      expect(keys.first, isNotNull);
      expect(keys.first, keys.last);
      model.dispose();
      await updates.controller.close();
      api.close();
      session.dispose();
    },
  );
}
