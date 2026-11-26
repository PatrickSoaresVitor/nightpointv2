import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nightpoint/core/api/api_client.dart';
import 'package:nightpoint/features/garage/data/garage_repository.dart';
import 'package:nightpoint/features/garage/presentation/garage_model.dart';
import 'package:nightpoint/features/garage/presentation/vehicle_detail_model.dart';

Map<String, Object?> vehicle({int version = 1, bool archived = false}) => {
  'id': 'synthetic-vehicle',
  'version': version,
  'brand': 'Synthetic',
  'model': 'Demo',
  'year': null,
  'color': null,
  'category': 'car',
  'primary': false,
  'archived': archived,
};

void main() {
  test(
    'garage creation and archive use API idempotency and version preconditions',
    () async {
      final session = ApiSession()..signIn('synthetic');
      var calls = 0;
      final api = ApiClient(
        ApiConfiguration('http://127.0.0.1:8000'),
        session,
        transport: MockClient((request) async {
          calls++;
          expect(request.headers['Authorization'], 'Bearer synthetic');
          expect(request.url.path, startsWith('/api/v1/me/vehicles'));
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body.containsKey('owner_id'), isFalse);
          if (request.method == 'POST') {
            expect(request.headers['Idempotency-Key'], 'same-key');
            return http.Response(jsonEncode(vehicle()), 201);
          }
          expect(request.method, 'PUT');
          expect(request.headers['If-Match'], '"1"');
          expect(body['archived'], isTrue);
          expect(body['primary'], isFalse);
          return http.Response(
            jsonEncode(vehicle(version: 2, archived: true)),
            200,
          );
        }),
      );
      final repository = GarageRepository(api);
      final created = await repository.create(
        VehicleRecord.fromJson(vehicle()).values(),
        'same-key',
      );
      final archived = await repository.update(
        created,
        created.values(isArchived: true, isPrimary: false),
      );
      expect(archived.archived, isTrue);
      expect(archived.version, 2);
      expect(calls, 2);
      api.close();
      session.dispose();
    },
  );

  test('garage list discards late response after disposal', () async {
    final session = ApiSession()..signIn('synthetic');
    final response = Completer<http.Response>();
    final api = ApiClient(
      ApiConfiguration('http://127.0.0.1:8000'),
      session,
      transport: MockClient((_) => response.future),
    );
    final model = GarageModel(GarageRepository(api));
    final pending = model.load();
    model.dispose();
    response.complete(
      http.Response(
        jsonEncode({
          'items': [vehicle()],
          'next_offset': null,
        }),
        200,
      ),
    );
    await pending;
    expect(model.items, isEmpty);
    api.close();
    session.dispose();
  });

  test(
    'stale garage mutation requires reload and never reports success',
    () async {
      final session = ApiSession()..signIn('synthetic');
      final api = ApiClient(
        ApiConfiguration('http://127.0.0.1:8000'),
        session,
        transport: MockClient((request) async {
          if (request.method == 'PUT') return http.Response('{}', 412);
          if (request.url.path.endsWith('/history')) {
            return http.Response('{"items":[],"next_offset":null}', 200);
          }
          return http.Response(jsonEncode(vehicle()), 200);
        }),
      );
      final model = VehicleDetailModel(
        GarageRepository(api),
        'synthetic-vehicle',
      );
      await model.load();
      await model.change(primary: true);
      expect(model.error, contains('Atualize'));
      expect(model.vehicle!.version, 1);
      expect(model.vehicle!.primary, isFalse);
      model.dispose();
      api.close();
      session.dispose();
    },
  );
}
