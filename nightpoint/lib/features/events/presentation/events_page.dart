import 'package:flutter/material.dart';

import '../../../core/api/api_client.dart';
import '../../community/presentation/community_page.dart';
import '../data/event_repository.dart';
import 'event_detail_page.dart';
import 'event_editor.dart';
import 'events_model.dart';

class EventsPage extends StatefulWidget {
  const EventsPage({
    super.key,
    required this.api,
    required this.userId,
    this.communityMode = false,
  });
  final ApiClient api;
  final String userId;
  final bool communityMode;
  @override
  State<EventsPage> createState() => _EventsPageState();
}

class _EventsPageState extends State<EventsPage> {
  late final EventsModel _model;
  final _filters = GlobalKey<FormState>();
  final _longitude = TextEditingController(text: '0.0');
  final _latitude = TextEditingController(text: '0.0');
  final _radius = TextEditingController(text: '10000');
  String? _category;
  late DateTime _from;

  @override
  void initState() {
    super.initState();
    _model = EventsModel(EventRepository(widget.api));
    _from = _model.from;
    _model.load(reset: true);
  }

  @override
  void dispose() {
    _model.dispose();
    _longitude.dispose();
    _latitude.dispose();
    _radius.dispose();
    super.dispose();
  }

  String? _number(String? value, double minimum, double maximum) {
    final number = double.tryParse(value ?? '');
    return number == null ||
            !number.isFinite ||
            number < minimum ||
            number > maximum
        ? 'Valor inválido.'
        : null;
  }

  Future<void> _date() async {
    final value = await showDatePicker(
      context: context,
      initialDate: _from,
      firstDate: DateTime(1),
      lastDate: DateTime(9999, 12, 31),
      helpText: 'Início da janela de 30 dias',
    );
    if (value != null && mounted) setState(() => _from = value.toUtc());
  }

  void _apply() {
    if (!_filters.currentState!.validate()) return;
    _model.configure(
      lon: double.parse(_longitude.text),
      lat: double.parse(_latitude.text),
      radiusM: double.parse(_radius.text),
      start: _from,
      categoryCode: _category,
    );
  }

  Future<void> _open(String identifier, {String? title}) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => widget.communityMode
            ? CommunityPage(
                api: widget.api,
                eventId: identifier,
                title: title ?? 'Encontro',
              )
            : EventDetailPage(
                api: widget.api,
                identifier: identifier,
                userId: widget.userId,
              ),
      ),
    );
    if (mounted) await _model.load(reset: true);
  }

  Future<void> _create() async {
    final created = await Navigator.of(context).push<EventRecord>(
      MaterialPageRoute(
        builder: (_) => EventEditor(repository: _model.repository),
      ),
    );
    if (created != null && mounted) await _open(created.id);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    floatingActionButton: widget.communityMode
        ? null
        : FloatingActionButton.extended(
            onPressed: _create,
            icon: const Icon(Icons.add),
            label: const Text('Criar encontro'),
          ),
    body: ListenableBuilder(
      listenable: _model,
      builder: (context, _) => RefreshIndicator(
        onRefresh: () => _model.load(reset: true),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
          children: [
            Text(
              widget.communityMode
                  ? 'Comunidade · escolha um encontro'
                  : 'Encontros',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: 16),
            SegmentedButton<bool>(
              segments: const [
                ButtonSegment(value: false, label: Text('Explorar')),
                ButtonSegment(value: true, label: Text('Meus encontros')),
              ],
              selected: {_model.owned},
              onSelectionChanged: _model.loading
                  ? null
                  : (values) => _model.changeMode(values.single),
            ),
            const SizedBox(height: 16),
            if (!_model.owned)
              ExpansionTile(
                title: const Text('Filtros e localização manual'),
                children: [
                  Form(
                    key: _filters,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      child: Column(
                        children: [
                          const Text(
                            'Use coordenadas sintéticas. Sua origem não é salva no catálogo.',
                          ),
                          const SizedBox(height: 16),
                          TextFormField(
                            controller: _longitude,
                            validator: (value) => _number(value, -180, 180),
                            keyboardType: const TextInputType.numberWithOptions(
                              signed: true,
                              decimal: true,
                            ),
                            decoration: const InputDecoration(
                              labelText: 'Longitude',
                            ),
                          ),
                          const SizedBox(height: 12),
                          TextFormField(
                            controller: _latitude,
                            validator: (value) => _number(value, -90, 90),
                            keyboardType: const TextInputType.numberWithOptions(
                              signed: true,
                              decimal: true,
                            ),
                            decoration: const InputDecoration(
                              labelText: 'Latitude',
                            ),
                          ),
                          const SizedBox(height: 12),
                          TextFormField(
                            controller: _radius,
                            validator: (value) => _number(value, 1, 50000),
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(
                              labelText: 'Raio em metros',
                            ),
                          ),
                          const SizedBox(height: 12),
                          DropdownButtonFormField<String>(
                            initialValue: _category,
                            isExpanded: true,
                            decoration: const InputDecoration(
                              labelText: 'Categoria',
                            ),
                            items: [
                              const DropdownMenuItem<String>(
                                value: null,
                                child: Text('Todas'),
                              ),
                              ...const [
                                'street',
                                'jdm',
                                'premium',
                                'drift',
                              ].map(
                                (value) => DropdownMenuItem(
                                  value: value,
                                  child: Text(value.toUpperCase()),
                                ),
                              ),
                            ],
                            onChanged: (value) =>
                                setState(() => _category = value),
                          ),
                          ListTile(
                            title: const Text('Início da janela de 30 dias'),
                            subtitle: Text(
                              _from.toLocal().toString().substring(0, 10),
                            ),
                            trailing: const Icon(Icons.calendar_today),
                            onTap: _date,
                          ),
                          FilledButton(
                            onPressed: _model.loading ? null : _apply,
                            child: const Text('Aplicar filtros'),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            if (_model.loading)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()),
              ),
            if (_model.error != null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    children: [
                      Text(_model.error!),
                      const SizedBox(height: 12),
                      OutlinedButton(
                        onPressed: () => _model.load(reset: true),
                        child: const Text('Tentar novamente'),
                      ),
                    ],
                  ),
                ),
              ),
            if (!_model.loading && _model.items.isEmpty && _model.error == null)
              const Card(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: Text(
                    'Nenhum encontro nesta busca. Você pode ajustar os filtros ou criar um encontro.',
                  ),
                ),
              ),
            ..._model.items.map(
              (event) => Card(
                child: ListTile(
                  contentPadding: const EdgeInsets.all(16),
                  leading: Icon(
                    event.visibility == 'owner_only'
                        ? Icons.lock_outline
                        : Icons.directions_car_outlined,
                  ),
                  title: Text(event.title),
                  subtitle: Text(
                    '${event.locationLabel}\n${event.startsAt.toLocal().toString().substring(0, 16)}',
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _open(event.id, title: event.title),
                ),
              ),
            ),
            if (_model.hasMore && !_model.loading)
              OutlinedButton(
                onPressed: _model.load,
                child: const Text('Carregar mais'),
              ),
          ],
        ),
      ),
    ),
  );
}
