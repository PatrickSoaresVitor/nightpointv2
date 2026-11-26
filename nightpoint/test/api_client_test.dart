import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nightpoint/core/api/api_client.dart';

class AbortObserver extends http.BaseClient {
  bool aborted = false;
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final signal = (request as http.Abortable).abortTrigger;
    expect(signal, isNotNull);
    await signal;
    aborted = true;
    throw http.RequestAbortedException(request.url);
  }
}

void main() {
  test(
    'academic configuration refuses external origins and embedded credentials',
    () {
      for (final value in [
        'https://example.com',
        'http://example.com',
        'http://a:b@localhost:8000',
        'http://localhost:8000/?token=x',
      ]) {
        expect(() => ApiConfiguration(value), throwsArgumentError);
      }
      expect(
        ApiConfiguration(
          'http://127.0.0.1:8000',
        ).endpoint('/api/v1/session').host,
        '127.0.0.1',
      );
    },
  );

  test(
    'authorization comes from session and JSON is sent through central adapter',
    () async {
      final session = ApiSession()..signIn('synthetic-token');
      final client = ApiClient(
        ApiConfiguration('http://localhost:8000'),
        session,
        transport: MockClient((request) async {
          expect(request.headers['Authorization'], 'Bearer synthetic-token');
          expect(jsonDecode(request.body), {'nickname': 'Synthetic'});
          return http.Response('{"version":1}', 200);
        }),
      );
      final response = await client.request(
        'PUT',
        '/api/v1/me/profile',
        body: {'nickname': 'Synthetic'},
        headers: {'Authorization': 'Bearer forged'},
      );
      expect(response.data['version'], 1);
      client.close();
    },
  );

  test('expired session is cleared and server details are not shown', () async {
    final session = ApiSession()..signIn('synthetic-token');
    final client = ApiClient(
      ApiConfiguration('http://localhost:8000'),
      session,
      transport: MockClient(
        (_) async => http.Response('{"detail":"private-sentinel"}', 401),
      ),
    );
    await expectLater(
      client.request('GET', '/api/v1/session'),
      throwsA(
        isA<ApiFailure>()
            .having((e) => e.status, 'status', 401)
            .having(
              (e) => e.message.contains('private-sentinel'),
              'redaction',
              false,
            ),
      ),
    );
    expect(session.signedIn, false);
    client.close();
  });

  test(
    'response from previous session cannot repopulate a logged out screen',
    () async {
      final response = Completer<http.Response>();
      final session = ApiSession()..signIn('synthetic-token');
      final client = ApiClient(
        ApiConfiguration('http://localhost:8000'),
        session,
        transport: MockClient((_) => response.future),
      );
      final pending = client.request('GET', '/api/v1/me/profile');
      session.signOut();
      response.complete(http.Response('{"nickname":"old-session"}', 200));
      await expectLater(
        pending,
        throwsA(isA<ApiFailure>().having((e) => e.status, 'stale', null)),
      );
      client.close();
    },
  );

  test(
    'network failure and timeout have useful non-sensitive messages',
    () async {
      final session = ApiSession()..signIn('synthetic-token');
      final client = ApiClient(
        ApiConfiguration('http://localhost:8000'),
        session,
        timeout: const Duration(milliseconds: 5),
        transport: MockClient((_) => Completer<http.Response>().future),
      );
      await expectLater(
        client.request('GET', '/api/v1/session'),
        throwsA(
          isA<ApiFailure>().having(
            (e) => e.message,
            'timeout',
            contains('demorou'),
          ),
        ),
      );
      client.close();
    },
  );

  test(
    'logout physically signals abortion to supported HTTP transports',
    () async {
      final transport = AbortObserver();
      final session = ApiSession()..signIn('synthetic-token');
      final client = ApiClient(
        ApiConfiguration('http://localhost:8000'),
        session,
        transport: transport,
      );
      final pending = client.request('GET', '/api/v1/me/profile');
      session.signOut();
      await expectLater(pending, throwsA(isA<ApiFailure>()));
      expect(transport.aborted, true);
      client.close();
    },
  );

  test(
    'route cancellation aborts only its operation and retains session',
    () async {
      final transport = AbortObserver();
      final session = ApiSession()..signIn('synthetic-token');
      final client = ApiClient(
        ApiConfiguration('http://localhost:8000'),
        session,
        transport: transport,
      );
      final operation = ApiCancellation();
      final pending = client.request(
        'GET',
        '/api/v1/me/profile',
        cancellation: operation,
      );
      operation.cancel();
      await expectLater(pending, throwsA(isA<ApiFailure>()));
      expect(transport.aborted, true);
      expect(session.signedIn, true);
      client.close();
    },
  );

  test('pagination query is encoded without changing API origin', () async {
    final session = ApiSession()..signIn('synthetic-token');
    final client = ApiClient(
      ApiConfiguration('http://127.0.0.1:8000'),
      session,
      transport: MockClient((request) async {
        expect(request.url.origin, 'http://127.0.0.1:8000');
        expect(request.url.path, '/api/v1/me/events');
        expect(request.url.queryParameters, {'offset': '25'});
        return http.Response('{"items":[],"next_offset":null}', 200);
      }),
    );
    await client.request('GET', '/api/v1/me/events', query: {'offset': '25'});
    client.close();
  });
}
