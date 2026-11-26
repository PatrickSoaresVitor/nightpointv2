import 'package:flutter/material.dart';

import '../../../core/api/api_client.dart';
import '../data/local_demo_identity.dart';

class LocalSignInPage extends StatefulWidget {
  const LocalSignInPage({super.key, required this.identity});
  final LocalDemoIdentity identity;
  @override
  State<LocalSignInPage> createState() => _LocalSignInPageState();
}

class _LocalSignInPageState extends State<LocalSignInPage> {
  bool _busy = false;
  String? _error;

  Future<void> _enter(String persona) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.identity.enter(persona);
    } on ApiFailure catch (failure) {
      if (mounted) setState(() => _error = failure.message);
    } on Exception {
      if (mounted) {
        setState(() => _error = 'Não foi possível iniciar a sessão local.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.directions_car_outlined,
                  size: 80,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 24),
                Text(
                  'NightPoint',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineLarge,
                ),
                const SizedBox(height: 12),
                const Text(
                  'Encontre sua comunidade. Viva o próximo encontro.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 32),
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(16),
                    child: Column(
                      children: [
                        Icon(Icons.science_outlined),
                        SizedBox(height: 8),
                        Text('Demonstração acadêmica local'),
                        SizedBox(height: 8),
                        Text(
                          'Somente participantes e dados sintéticos. Não use credenciais de pessoas reais.',
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 24),
                FilledButton.icon(
                  onPressed: _busy ? null : () => _enter('participant-a'),
                  icon: const Icon(Icons.person_outline),
                  label: const Text('Entrar como participante A'),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: _busy ? null : () => _enter('participant-b'),
                  icon: const Icon(Icons.person_outline),
                  label: const Text('Entrar como participante B'),
                ),
                if (_busy)
                  const Padding(
                    padding: EdgeInsets.all(16),
                    child: Center(child: CircularProgressIndicator()),
                  ),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: Text(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
