import '../../../core/api/api_client.dart';

/// Explicit synthetic server composition, never a fallback for real identity.
class LocalDemoIdentity {
  const LocalDemoIdentity(this.api);
  final ApiClient api;

  Future<void> enter(String persona) async {
    if (!{'participant-a', 'participant-b'}.contains(persona)) {
      throw const ApiFailure(null, 'Participante sintético inválido.');
    }
    final response = await api.request(
      'POST',
      '/api/v1/demo/session',
      authenticated: false,
      body: {'persona': persona},
    );
    final data = response.data;
    if (data is! Map<String, dynamic> ||
        data['mode'] != 'synthetic' ||
        data['access_token'] is! String) {
      throw const ApiFailure(null, 'Ambiente de demonstração indisponível.');
    }
    api.session.signIn(data['access_token'] as String);
  }

  Future<void> leave() async {
    try {
      await api.request('POST', '/api/v1/demo/logout');
    } finally {
      api.session.signOut();
    }
  }
}
