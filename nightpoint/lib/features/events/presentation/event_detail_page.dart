import 'package:flutter/material.dart';

import '../../../core/api/api_client.dart';
import '../../community/presentation/community_page.dart';
import '../data/event_repository.dart';
import '../data/event_updates.dart';
import 'event_detail_model.dart';
import 'event_editor.dart';

class EventDetailPage extends StatefulWidget {
  const EventDetailPage({
    super.key,
    required this.api,
    required this.identifier,
    required this.userId,
  });
  final ApiClient api;
  final String identifier, userId;

  @override
  State<EventDetailPage> createState() => _EventDetailPageState();
}

class _EventDetailPageState extends State<EventDetailPage>
    with WidgetsBindingObserver {
  late final EventDetailModel _model;
  bool _foreground = true, _routeActive = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _model = EventDetailModel(
      widget.identifier,
      EventRepository(widget.api),
      EventUpdates(widget.api.configuration, widget.api.session),
    )..start();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    if (_foreground && _routeActive) {
      _model.start();
    } else {
      _model.suspend();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _model.dispose();
    super.dispose();
  }

  Future<void> _edit(EventRecord previous) async {
    _routeActive = false;
    _model.suspend();
    try {
      await Navigator.of(context).push<EventRecord>(
        MaterialPageRoute(
          builder: (_) =>
              EventEditor(repository: _model.repository, previous: previous),
        ),
      );
    } finally {
      if (mounted) {
        _routeActive = true;
        if (_foreground) _model.start();
      }
    }
  }

  Future<void> _community(EventRecord event) async {
    _routeActive = false;
    _model.suspend();
    try {
      await Navigator.of(context).push<void>(
        MaterialPageRoute(
          builder: (_) => CommunityPage(
            api: widget.api,
            eventId: event.id,
            title: event.title,
          ),
        ),
      );
    } finally {
      if (mounted) {
        _routeActive = true;
        if (_foreground) _model.start();
      }
    }
  }

  Future<void> _cancel() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Cancelar encontro?'),
        content: const Text(
          'O encontro sai da descoberta. Seu histórico permanece disponível para você.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Voltar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Cancelar encontro'),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted) await _model.cancel();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Encontro'),
      actions: [
        IconButton(
          tooltip: 'Atualizar',
          onPressed: _model.reload,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: ListenableBuilder(
      listenable: _model,
      builder: (context, _) {
        final event = _model.event;
        if (event == null && _model.loading) {
          return const Center(child: CircularProgressIndicator());
        }
        if (event == null) {
          return Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(_model.error ?? 'Conteúdo indisponível.'),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: _model.reload,
                    child: const Text('Tentar novamente'),
                  ),
                ],
              ),
            ),
          );
        }
        final owner = event.organizerId == widget.userId;
        return RefreshIndicator(
          onRefresh: _model.reload,
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              if (_model.loading) const LinearProgressIndicator(),
              Icon(
                event.visibility == 'owner_only'
                    ? Icons.lock_outline
                    : Icons.groups_outlined,
                size: 52,
              ),
              const SizedBox(height: 24),
              Text(
                event.title,
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                children: [
                  Chip(label: Text(event.category.toUpperCase())),
                  Chip(
                    label: Text(
                      event.state == 'cancelled' ? 'Cancelado' : 'Publicado',
                    ),
                  ),
                  if (event.visibility == 'owner_only')
                    const Chip(label: Text('Somente você')),
                ],
              ),
              const SizedBox(height: 16),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.schedule),
                title: Text(
                  event.startsAt.toLocal().toString().substring(0, 16),
                ),
                subtitle: const Text('Horário local'),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.place_outlined),
                title: Text(event.locationLabel),
                subtitle: Text('${event.latitude}, ${event.longitude}'),
              ),
              if (event.description != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Text(event.description!),
                ),
              if (_model.error != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Text(
                    _model.error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: () => _community(event),
                icon: const Icon(Icons.forum_outlined),
                label: const Text('Curtidas, participações e comentários'),
              ),
              if (owner && event.state == 'published') ...[
                const SizedBox(height: 24),
                FilledButton.icon(
                  onPressed: _model.mutating ? null : () => _edit(event),
                  icon: const Icon(Icons.edit_outlined),
                  label: const Text('Editar encontro'),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: _model.mutating ? null : _cancel,
                  icon: const Icon(Icons.cancel_outlined),
                  label: const Text('Cancelar encontro'),
                ),
              ],
            ],
          ),
        );
      },
    ),
  );
}
