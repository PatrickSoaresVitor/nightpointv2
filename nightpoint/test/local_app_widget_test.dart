import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nightpoint/app/nightpoint_api_app.dart';
import 'package:nightpoint/core/api/api_client.dart';
import 'package:nightpoint/features/events/data/event_repository.dart';
import 'package:nightpoint/features/events/presentation/event_editor.dart';

void main() {
  testWidgets(
    'session change discards nested private routes and previous account data',
    (tester) async {
      final session = ApiSession()..signIn('account-a-token');
      final api = ApiClient(
        ApiConfiguration('http://localhost:8000'),
        session,
        transport: MockClient(
          (request) async => http.Response(
            jsonEncode({
              'user_id': '00000000-0000-4000-8000-000000000001',
              'nickname':
                  request.headers['Authorization'] == 'Bearer account-a-token'
                  ? 'Account A'
                  : 'Account B',
              'avatar_style': null,
              'avatar_seed': null,
              'version': 1,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          ),
        ),
      );
      await tester.pumpWidget(NightPointApiApp(api: api));
      await tester.pumpAndSettle();
      Navigator.of(tester.element(find.text('Olá, Account A'))).push<void>(
        MaterialPageRoute(
          builder: (_) => const Scaffold(body: Text('private-sentinel')),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('private-sentinel'), findsOneWidget);
      session.signOut();
      await tester.pumpAndSettle();
      expect(find.text('private-sentinel'), findsNothing);
      expect(find.text('Entrar como participante A'), findsOneWidget);
      session.signIn('account-b-token');
      await tester.pumpAndSettle();
      expect(find.text('Olá, Account B'), findsOneWidget);
      expect(find.text('private-sentinel'), findsNothing);
      expect(find.text('Olá, Account A'), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
      api.close();
      session.dispose();
    },
  );

  testWidgets(
    'synthetic entry requires explicit profile command and logout clears UI',
    (tester) async {
      final session = ApiSession();
      var enrolled = false;
      final calls = <String>[];
      final transport = MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.url.path == '/api/v1/demo/session') {
          expect(request.headers.containsKey('Authorization'), false);
          return http.Response(
            '{"mode":"synthetic","access_token":"synthetic-session"}',
            200,
          );
        }
        expect(request.headers['Authorization'], 'Bearer synthetic-session');
        if (request.method == 'GET' &&
            request.url.path == '/api/v1/me/profile' &&
            !enrolled) {
          return http.Response('{}', 409);
        }
        if (request.method == 'PUT' &&
            request.url.path == '/api/v1/me/profile') {
          enrolled = true;
          expect(jsonDecode(request.body)['nickname'], 'Participante A');
          return http.Response(
            jsonEncode({
              'user_id': '00000000-0000-4000-8000-000000000001',
              'nickname': 'Participante A',
              'avatar_style': null,
              'avatar_seed': null,
              'version': 1,
            }),
            201,
          );
        }
        if (request.url.path == '/api/v1/demo/logout') {
          return http.Response('', 204);
        }
        fail(
          'Unexpected request in the inactive journey: ${request.method} ${request.url.path}',
        );
      });
      final api = ApiClient(
        ApiConfiguration('http://127.0.0.1:8000'),
        session,
        transport: transport,
      );
      await tester.pumpWidget(NightPointApiApp(api: api));
      await tester.ensureVisible(find.text('Entrar como participante A'));
      await tester.tap(find.text('Entrar como participante A'));
      await tester.pumpAndSettle();
      expect(enrolled, false);
      expect(find.text('Salvar perfil'), findsOneWidget);
      await tester.enterText(
        find.byType(TextFormField).first,
        'Participante A',
      );
      await tester.ensureVisible(find.text('Salvar perfil'));
      await tester.tap(find.text('Salvar perfil'));
      await tester.pumpAndSettle();
      expect(enrolled, true);
      expect(find.text('Olá, Participante A'), findsOneWidget);
      expect(calls.any((value) => value.contains('/discovery/')), false);
      await tester.tap(find.text('Perfil'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('Sair'),
        250,
        scrollable: find.byType(Scrollable).first,
      );
      final logoutButton = find.ancestor(
        of: find.text('Sair'),
        matching: find.byWidgetPredicate((widget) => widget is ButtonStyleButton),
      ).first;
      await Scrollable.ensureVisible(tester.element(logoutButton), alignment: .5);
      await tester.pumpAndSettle();
      await tester.tap(logoutButton);
      await tester.pumpAndSettle();
      expect(session.signedIn, false);
      expect(find.text('Entrar como participante A'), findsOneWidget);
      expect(calls.last, 'POST /api/v1/demo/logout');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      api.close();
      session.dispose();
    },
  );

  testWidgets('unavailable identity is shown without server details', (
    tester,
  ) async {
    final session = ApiSession();
    final api = ApiClient(
      ApiConfiguration('http://localhost:8000'),
      session,
      transport: MockClient(
        (_) async => http.Response('{"detail":"private-sentinel"}', 503),
      ),
    );
    await tester.pumpWidget(NightPointApiApp(api: api));
    await tester.ensureVisible(find.text('Entrar como participante A'));
    await tester.tap(find.text('Entrar como participante A'));
    await tester.pumpAndSettle();
    expect(find.text('Serviço temporariamente indisponível.'), findsOneWidget);
    expect(find.textContaining('private-sentinel'), findsNothing);
    expect(session.signedIn, false);
    await tester.pumpWidget(const SizedBox.shrink());
    api.close();
    session.dispose();
  });

  testWidgets(
    'creation retry retains idempotency key and returns saved event',
    (tester) async {
      final session = ApiSession()..signIn('synthetic-session');
      final keys = <String>[];
      EventRecord? saved;
      final api = ApiClient(
        ApiConfiguration('http://localhost:8000'),
        session,
        transport: MockClient((request) async {
          expect(request.method, 'POST');
          expect(request.url.path, '/api/v1/events');
          keys.add(request.headers['Idempotency-Key']!);
          if (keys.length == 1) return http.Response('{}', 503);
          final values = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(
            jsonEncode({
              ...values,
              'id': '00000000-0000-4000-8000-000000000002',
              'organizer_id': '00000000-0000-4000-8000-000000000001',
              'version': 1,
              'state': 'published',
            }),
            201,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: FilledButton(
                onPressed: () async {
                  saved = await Navigator.of(context).push<EventRecord>(
                    MaterialPageRoute(
                      builder: (_) =>
                          EventEditor(repository: EventRepository(api)),
                    ),
                  );
                },
                child: const Text('Novo encontro'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Novo encontro'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Título'),
        'Encontro sintético',
      );
      await tester.scrollUntilVisible(
        find.text('Salvar encontro'),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      await Scrollable.ensureVisible(
        tester.element(
          find
              .ancestor(
                of: find.text('Salvar encontro'),
                matching: find.byWidgetPredicate(
                  (widget) => widget is ButtonStyleButton,
                ),
              )
              .first,
        ),
        alignment: 0.5,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Salvar encontro'));
      await tester.pumpAndSettle();
      expect(
        find.text('Serviço temporariamente indisponível.'),
        findsOneWidget,
      );
      await tester.scrollUntilVisible(
        find.text('Salvar encontro'),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      await Scrollable.ensureVisible(
        tester.element(
          find
              .ancestor(
                of: find.text('Salvar encontro'),
                matching: find.byWidgetPredicate(
                  (widget) => widget is ButtonStyleButton,
                ),
              )
              .first,
        ),
        alignment: 0.5,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Salvar encontro'));
      await tester.pumpAndSettle();
      expect(keys.length, 2);
      expect(keys[0], keys[1]);
      expect(saved?.title, 'Encontro sintético');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      api.close();
      session.dispose();
    },
  );
}
