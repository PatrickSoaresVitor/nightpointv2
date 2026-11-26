import 'package:flutter/material.dart';

import 'app/nightpoint_api_app.dart';
import 'core/api/api_client.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  const synthetic = bool.fromEnvironment('NP_SYNTHETIC', defaultValue: false);
  const address = String.fromEnvironment('NP_API_URL');
  if (!synthetic || address.isEmpty) {
    runApp(
      const MaterialApp(
        home: Scaffold(
          body: Center(
            child: Text(
              'Ambiente local não habilitado. Consulte as instruções de execução.',
            ),
          ),
        ),
      ),
    );
    return;
  }
  try {
    runApp(_LocalRuntime(configuration: ApiConfiguration(address)));
  } on FormatException {
    runApp(
      const MaterialApp(
        home: Scaffold(
          body: Center(child: Text('Configuração local inválida.')),
        ),
      ),
    );
  } on ArgumentError {
    runApp(
      const MaterialApp(
        home: Scaffold(
          body: Center(child: Text('Configuração local inválida.')),
        ),
      ),
    );
  }
}

class _LocalRuntime extends StatefulWidget {
  const _LocalRuntime({required this.configuration});
  final ApiConfiguration configuration;
  @override
  State<_LocalRuntime> createState() => _LocalRuntimeState();
}

class _LocalRuntimeState extends State<_LocalRuntime> {
  late final ApiSession _session;
  late final ApiClient _api;
  @override
  void initState() {
    super.initState();
    _session = ApiSession();
    _api = ApiClient(widget.configuration, _session);
  }

  @override
  void dispose() {
    _api.close();
    _session.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => NightPointApiApp(api: _api);
}
