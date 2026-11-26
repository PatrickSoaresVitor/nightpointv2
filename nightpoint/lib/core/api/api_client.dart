import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// The academic composition connects only to the explicitly configured local API.
class ApiConfiguration {
  ApiConfiguration(String address) : base = Uri.parse(address) {
    if (base.scheme != 'http' ||
        !{'localhost', '127.0.0.1', '::1', '10.0.2.2'}.contains(base.host) ||
        base.userInfo.isNotEmpty ||
        base.hasQuery ||
        base.hasFragment ||
        (base.path.isNotEmpty && base.path != '/')) {
      throw ArgumentError('Informe a API local autorizada, sem credenciais.');
    }
  }

  final Uri base;

  Uri endpoint(String path) {
    if (!path.startsWith('/api/v1/') ||
        path.contains('..') ||
        path.contains('?')) {
      throw ArgumentError('Caminho da API inválido.');
    }
    final result = base.resolve(path);
    if (result.origin != base.origin) throw ArgumentError('Origem inválida.');
    return result;
  }
}

/// Tokens remain in memory; the identity provider owns durable credentials.
class ApiSession extends ChangeNotifier {
  String? _token;
  int _generation = 0;
  String? get token => _token;
  int get generation => _generation;
  bool get signedIn => _token != null;

  void signIn(String token) {
    if (!RegExp(r'^[A-Za-z0-9_\-.]{1,8192}$').hasMatch(token)) {
      throw ArgumentError('Sessão inválida.');
    }
    _token = token;
    _generation++;
    notifyListeners();
  }

  void signOut() {
    _token = null;
    _generation++;
    notifyListeners();
  }
}

class ApiFailure implements Exception {
  const ApiFailure(this.status, this.message, {this.correlationId});
  final int? status;
  final String message;
  final String? correlationId;
  @override
  String toString() => message;
}

class ApiResponse {
  const ApiResponse(this.data, this.headers);
  final dynamic data;
  final Map<String, String> headers;
}

class ApiCancellation {
  final Completer<void> _signal = Completer<void>();
  Future<void> get whenCancelled => _signal.future;
  bool get isCancelled => _signal.isCompleted;
  void cancel() {
    if (!_signal.isCompleted) _signal.complete();
  }
}

class ApiClient {
  ApiClient(
    this.configuration,
    this.session, {
    http.Client? transport,
    this.timeout = const Duration(seconds: 10),
  }) : _transport = transport ?? http.Client() {
    session.addListener(_abortPending);
  }

  final ApiConfiguration configuration;
  final ApiSession session;
  final http.Client _transport;
  final Duration timeout;
  bool _closed = false;
  final Set<Completer<void>> _pending = {};

  void _abortPending() {
    for (final pending in _pending.toList()) {
      if (!pending.isCompleted) pending.complete();
    }
  }

  Future<ApiResponse> request(
    String method,
    String path, {
    Object? body,
    Map<String, String> headers = const {},
    Map<String, String> query = const {},
    bool authenticated = true,
    ApiCancellation? cancellation,
  }) async {
    if (_closed) throw const ApiFailure(null, 'Conexão encerrada.');
    if (cancellation?.isCancelled == true) {
      throw const ApiFailure(null, 'Solicitação cancelada.');
    }
    final generation = session.generation;
    final token = session.token;
    if (authenticated && token == null) {
      throw const ApiFailure(401, 'Entre para continuar.');
    }
    final endpoint = configuration.endpoint(path);
    final abort = Completer<void>();
    final triggers = <Future<void>>[abort.future];
    if (cancellation != null) triggers.add(cancellation.whenCancelled);
    final request = http.AbortableRequest(
      method,
      query.isEmpty ? endpoint : endpoint.replace(queryParameters: query),
      abortTrigger: Future.any(triggers),
    );
    request.headers.addAll({'Accept': 'application/json', ...headers});
    // The caller cannot forge identity through an arbitrary header.
    request.headers.remove('Authorization');
    if (authenticated) request.headers['Authorization'] = 'Bearer $token';
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    _pending.add(abort);
    try {
      final response = await (() async {
        final stream = await _transport.send(request);
        return http.Response.fromStream(stream);
      })().timeout(timeout);
      if (generation != session.generation ||
          _closed ||
          cancellation?.isCancelled == true) {
        throw const ApiFailure(null, 'Sessão alterada; atualize os dados.');
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        if (response.statusCode == 401 && authenticated) session.signOut();
        final correlation = response.headers['x-correlation-id'];
        throw ApiFailure(
          response.statusCode,
          _message(response.statusCode),
          correlationId:
              correlation != null &&
                  RegExp(r'^[0-9a-f]{32}$').hasMatch(correlation)
              ? correlation
              : null,
        );
      }
      return ApiResponse(
        response.body.isEmpty ? null : jsonDecode(response.body),
        response.headers,
      );
    } on TimeoutException {
      if (!abort.isCompleted) abort.complete();
      throw const ApiFailure(
        null,
        'A API demorou a responder. Tente novamente.',
      );
    } on http.RequestAbortedException {
      throw const ApiFailure(null, 'Solicitação cancelada.');
    } on http.ClientException {
      throw const ApiFailure(null, 'Não foi possível conectar à API local.');
    } on FormatException {
      throw const ApiFailure(null, 'Resposta inválida da API.');
    } finally {
      _pending.remove(abort);
    }
  }

  static String _message(int status) => switch (status) {
    401 => 'Sua sessão expirou. Entre novamente.',
    403 => 'Esta ação não está disponível para sua conta.',
    404 => 'Conteúdo indisponível ou sem permissão.',
    409 => 'Conflito de dados. Verifique seu perfil ou atualize a tela.',
    412 => 'Os dados mudaram. Atualize antes de salvar.',
    422 => 'Confira os campos informados.',
    429 => 'Muitas solicitações. Aguarde e tente novamente.',
    503 => 'Serviço temporariamente indisponível.',
    _ => 'Não foi possível concluir a solicitação.',
  };

  void close() {
    _closed = true;
    session.removeListener(_abortPending);
    _abortPending();
    _transport.close();
  }
}
