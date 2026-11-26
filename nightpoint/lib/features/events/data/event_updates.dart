import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../../core/api/api_client.dart';

Stream<List<int>> _boundedLines(Stream<List<int>> source) async* {
  var lineBytes = 0;
  await for (final chunk in source) {
    for (final byte in chunk) {
      lineBytes = byte == 10 ? 0 : lineBytes + 1;
      if (lineBytes > 8192) {
        throw const FormatException('Event frame exceeds limit');
      }
    }
    yield chunk;
  }
}

/// Per-detail invalidation only. REST remains the source of event data.
class EventUpdates {
  EventUpdates(
    this.configuration,
    this.session, {
    http.Client Function()? transport,
  }) : _transport = transport ?? http.Client.new;
  final ApiConfiguration configuration;
  final ApiSession session;
  final http.Client Function() _transport;

  Stream<int> watch(String eventId) {
    http.Client? active;
    bool stopped = false;
    int? lastVersion;
    int reconnect = 0;
    final generation = session.generation;
    late StreamController<int> controller;

    void changedSession() {
      if (session.generation != generation) {
        stopped = true;
        active?.close();
        if (!controller.isClosed) unawaited(controller.close());
      }
    }

    Future<void> run() async {
      while (!stopped && session.generation == generation && session.signedIn) {
        final client = _transport();
        active = client;
        try {
          final request = http.Request(
            'GET',
            configuration.endpoint(
              '/api/v1/events/${Uri.encodeComponent(eventId)}/updates',
            ),
          );
          request.headers.addAll({
            'Authorization': 'Bearer ${session.token}',
            'Accept': 'text/event-stream',
            if (lastVersion != null) 'Last-Event-ID': '$lastVersion',
          });
          final response = await client
              .send(request)
              .timeout(const Duration(seconds: 10));
          if (response.statusCode == 401) {
            if (session.generation == generation) session.signOut();
            break;
          }
          if (response.statusCode == 403 || response.statusCode == 404) {
            controller.addError(
              const ApiFailure(404, 'Conteúdo indisponível ou sem permissão.'),
            );
            break;
          }
          if (response.statusCode != 200 ||
              !(response.headers['content-type'] ?? '').startsWith(
                'text/event-stream',
              )) {
            throw const ApiFailure(
              null,
              'Atualização temporariamente indisponível.',
            );
          }
          reconnect = 0;
          String event = '';
          String data = '';
          // A quiet/broken stream must reconnect and force a REST resync.
          await for (final line
              in _boundedLines(response.stream)
                  .timeout(const Duration(seconds: 20))
                  .transform(utf8.decoder)
                  .transform(const LineSplitter())) {
            if (stopped || session.generation != generation) break;
            if (line.length > 8192 || data.length > 8192) {
              throw const ApiFailure(null, 'Atualização inválida.');
            }
            if (line.startsWith('event:')) event = line.substring(6).trim();
            if (line.startsWith('data:')) data += line.substring(5).trim();
            if (line.isEmpty) {
              if (event == 'session-expired') {
                // The server also ends a healthy stream at its short lease.
                // Reconnect to revalidate; only an actual HTTP 401 logs out.
                break;
              }
              if (event == 'changed' || event == 'resync') {
                final payload = jsonDecode(data);
                if (payload is! Map<String, dynamic>) {
                  throw const FormatException('Invalid event frame');
                }
                final version = payload['version'];
                if (version is int &&
                    version > 0 &&
                    (event == 'resync' ||
                        lastVersion == null ||
                        version > lastVersion!)) {
                  lastVersion = version;
                  controller.add(version);
                }
              }
              event = '';
              data = '';
            }
          }
        } on Exception {
          // No upstream error text, URL, token or body enters UI/logs.
          if (!stopped && !controller.isClosed) {
            controller.addError(
              const ApiFailure(null, 'Reconectando às atualizações.'),
            );
          }
        } finally {
          client.close();
          active = null;
        }
        if (!stopped) {
          reconnect = (reconnect + 1).clamp(1, 5);
          await Future<void>.delayed(Duration(seconds: reconnect));
        }
      }
      session.removeListener(changedSession);
      if (!controller.isClosed) await controller.close();
    }

    controller = StreamController<int>(
      onListen: () {
        session.addListener(changedSession);
        unawaited(run());
      },
      onCancel: () {
        stopped = true;
        session.removeListener(changedSession);
        active?.close();
      },
    );
    return controller.stream;
  }
}
